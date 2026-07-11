use std::fs::File;
use std::io::{Read, Seek, SeekFrom};

use crate::error::HelperError;

const OGG_CRC_POLYNOMIAL: u32 = 0x04c1_1db7;
const MAX_PACKET_BYTES: usize = 1024 * 1024;

#[derive(Debug, Clone, PartialEq)]
pub struct OggSummary {
    pub bytes: u64,
    pub pages: u32,
    pub packets: u64,
    pub channels: u8,
    pub sample_rate: u32,
    pub duration_seconds: f64,
}

pub fn validate_ogg_vorbis(file: &mut File) -> Result<OggSummary, HelperError> {
    let file_size = file
        .metadata()
        .map_err(|_| HelperError::Io("could not inspect temporary output"))?
        .len();
    if file_size < 27 {
        return Err(HelperError::InvalidOgg("file is too small"));
    }
    file.seek(SeekFrom::Start(0))
        .map_err(|_| HelperError::Io("could not validate temporary output"))?;

    let mut position = 0_u64;
    let mut pages = 0_u32;
    let mut packets = 0_u64;
    let mut stream_serial = None;
    let mut expected_sequence = 0_u32;
    let mut pending_packet = Vec::new();
    let mut found_eos = false;
    let mut last_granule = 0_u64;
    let mut channels = 0_u8;
    let mut sample_rate = 0_u32;

    while position < file_size {
        if found_eos {
            return Err(HelperError::InvalidOgg("data appears after the EOS page"));
        }
        let mut header = [0_u8; 27];
        file.read_exact(&mut header)
            .map_err(|_| HelperError::InvalidOgg("page header is truncated"))?;
        if &header[0..4] != b"OggS" || header[4] != 0 {
            return Err(HelperError::InvalidOgg(
                "page capture pattern or version is invalid",
            ));
        }

        let flags = header[5];
        if flags & !0x07 != 0 {
            return Err(HelperError::InvalidOgg("page contains unknown flags"));
        }
        let granule = u64::from_le_bytes(
            header[6..14]
                .try_into()
                .map_err(|_| HelperError::InvalidOgg("granule position is invalid"))?,
        );
        let serial = u32::from_le_bytes(
            header[14..18]
                .try_into()
                .map_err(|_| HelperError::InvalidOgg("stream serial is invalid"))?,
        );
        let sequence = u32::from_le_bytes(
            header[18..22]
                .try_into()
                .map_err(|_| HelperError::InvalidOgg("page sequence is invalid"))?,
        );
        let stored_crc = u32::from_le_bytes(
            header[22..26]
                .try_into()
                .map_err(|_| HelperError::InvalidOgg("page CRC is invalid"))?,
        );
        let segment_count = header[26] as usize;
        let mut lacing = vec![0_u8; segment_count];
        file.read_exact(&mut lacing)
            .map_err(|_| HelperError::InvalidOgg("lacing table is truncated"))?;
        let body_len = lacing
            .iter()
            .try_fold(0_usize, |total, value| total.checked_add(*value as usize))
            .ok_or(HelperError::InvalidOgg("page body size overflowed"))?;
        let mut body = vec![0_u8; body_len];
        file.read_exact(&mut body)
            .map_err(|_| HelperError::InvalidOgg("page body is truncated"))?;

        let page_len = 27_u64 + segment_count as u64 + body_len as u64;
        if position.saturating_add(page_len) > file_size {
            return Err(HelperError::InvalidOgg("page exceeds file bounds"));
        }
        let mut page = Vec::with_capacity(page_len as usize);
        page.extend_from_slice(&header);
        page.extend_from_slice(&lacing);
        page.extend_from_slice(&body);
        page[22..26].fill(0);
        if ogg_crc(&page) != stored_crc {
            return Err(HelperError::InvalidOgg("page CRC does not match"));
        }

        if pages == 0 {
            if flags & 0x02 == 0 || flags & 0x01 != 0 || sequence != 0 {
                return Err(HelperError::InvalidOgg(
                    "first page is not a valid BOS page",
                ));
            }
            stream_serial = Some(serial);
        } else {
            if flags & 0x02 != 0 {
                return Err(HelperError::InvalidOgg("BOS appears after the first page"));
            }
            if stream_serial != Some(serial) {
                return Err(HelperError::InvalidOgg(
                    "multiple logical streams are not supported",
                ));
            }
        }
        if sequence != expected_sequence {
            return Err(HelperError::InvalidOgg("page sequence is not continuous"));
        }
        expected_sequence = expected_sequence.wrapping_add(1);

        let continued = flags & 0x01 != 0;
        if continued == pending_packet.is_empty() {
            return Err(HelperError::InvalidOgg(
                "packet continuation flag is inconsistent",
            ));
        }
        let mut body_offset = 0_usize;
        for segment_len in lacing {
            let segment_len = segment_len as usize;
            let end = body_offset + segment_len;
            if pending_packet.len().saturating_add(segment_len) > MAX_PACKET_BYTES {
                return Err(HelperError::InvalidOgg("packet exceeds 1 MiB"));
            }
            pending_packet.extend_from_slice(&body[body_offset..end]);
            body_offset = end;
            if segment_len < 255 {
                if packets < 3 {
                    let (parsed_channels, parsed_rate) =
                        validate_vorbis_header(packets as usize, &pending_packet)?;
                    if packets == 0 {
                        channels = parsed_channels;
                        sample_rate = parsed_rate;
                    }
                }
                packets += 1;
                pending_packet.clear();
            }
        }

        if granule != u64::MAX {
            if granule < last_granule {
                return Err(HelperError::InvalidOgg("granule positions move backwards"));
            }
            last_granule = granule;
        }
        if flags & 0x04 != 0 {
            if !pending_packet.is_empty() {
                return Err(HelperError::InvalidOgg("EOS ends inside a packet"));
            }
            found_eos = true;
        }

        pages = pages
            .checked_add(1)
            .ok_or(HelperError::InvalidOgg("page count overflowed"))?;
        position += page_len;
    }

    if position != file_size
        || !found_eos
        || !pending_packet.is_empty()
        || packets < 4
        || channels == 0
        || sample_rate == 0
        || last_granule == 0
    {
        return Err(HelperError::InvalidOgg("stream is incomplete"));
    }

    Ok(OggSummary {
        bytes: file_size,
        pages,
        packets,
        channels,
        sample_rate,
        duration_seconds: last_granule as f64 / sample_rate as f64,
    })
}

fn validate_vorbis_header(index: usize, packet: &[u8]) -> Result<(u8, u32), HelperError> {
    let expected_type = [1_u8, 3, 5]
        .get(index)
        .ok_or(HelperError::InvalidOgg("too many Vorbis headers"))?;
    if packet.len() < 8 || packet[0] != *expected_type || &packet[1..7] != b"vorbis" {
        return Err(HelperError::InvalidOgg(
            "Vorbis header signature is invalid",
        ));
    }

    if index == 0 {
        if packet.len() < 30
            || u32::from_le_bytes(
                packet[7..11]
                    .try_into()
                    .map_err(|_| HelperError::InvalidOgg("Vorbis version is invalid"))?,
            ) != 0
            || packet[29] & 0x01 == 0
        {
            return Err(HelperError::InvalidOgg(
                "Vorbis identification header is invalid",
            ));
        }
        let channels = packet[11];
        let sample_rate = u32::from_le_bytes(
            packet[12..16]
                .try_into()
                .map_err(|_| HelperError::InvalidOgg("Vorbis sample rate is invalid"))?,
        );
        if !(1..=8).contains(&channels) || !(8_000..=384_000).contains(&sample_rate) {
            return Err(HelperError::InvalidOgg(
                "Vorbis audio shape is out of bounds",
            ));
        }
        return Ok((channels, sample_rate));
    }

    if packet.last().is_none_or(|byte| byte & 0x01 == 0) {
        return Err(HelperError::InvalidOgg(
            "Vorbis header framing bit is missing",
        ));
    }
    Ok((0, 0))
}

fn ogg_crc(page: &[u8]) -> u32 {
    let mut crc = 0_u32;
    for byte in page {
        crc ^= u32::from(*byte) << 24;
        for _ in 0..8 {
            crc = if crc & 0x8000_0000 != 0 {
                (crc << 1) ^ OGG_CRC_POLYNOMIAL
            } else {
                crc << 1
            };
        }
    }
    crc
}

#[cfg(test)]
pub(crate) fn synthetic_ogg() -> Vec<u8> {
    let mut identification = vec![0_u8; 30];
    identification[0] = 1;
    identification[1..7].copy_from_slice(b"vorbis");
    identification[11] = 2;
    identification[12..16].copy_from_slice(&44_100_u32.to_le_bytes());
    identification[28] = 0xb8;
    identification[29] = 1;

    let mut comment = Vec::from(&b"\x03vorbis"[..]);
    comment.extend_from_slice(&0_u32.to_le_bytes());
    comment.extend_from_slice(&0_u32.to_le_bytes());
    comment.push(1);
    let mut setup = Vec::from(&b"\x05vorbis"[..]);
    setup.push(1);
    let audio = [0_u8; 16];
    let packets: [&[u8]; 4] = [&identification, &comment, &setup, &audio];

    let mut page = vec![0_u8; 27];
    page[0..4].copy_from_slice(b"OggS");
    page[5] = 0x02 | 0x04;
    page[6..14].copy_from_slice(&44_100_u64.to_le_bytes());
    page[14..18].copy_from_slice(&7_u32.to_le_bytes());
    page[26] = packets.len() as u8;
    for packet in packets {
        page.push(packet.len() as u8);
    }
    for packet in packets {
        page.extend_from_slice(packet);
    }
    let crc = ogg_crc(&page);
    page[22..26].copy_from_slice(&crc.to_le_bytes());
    page
}

#[cfg(test)]
mod tests {
    use std::io::{Seek, Write};

    use tempfile::NamedTempFile;

    use super::*;

    #[test]
    fn accepts_structurally_complete_vorbis_stream() {
        let mut file = NamedTempFile::new().expect("temp output");
        file.write_all(&synthetic_ogg()).expect("write Ogg");
        file.as_file_mut().rewind().expect("rewind");
        let summary = validate_ogg_vorbis(file.as_file_mut()).expect("valid Ogg");
        assert_eq!(summary.pages, 1);
        assert_eq!(summary.packets, 4);
        assert_eq!(summary.channels, 2);
        assert_eq!(summary.sample_rate, 44_100);
        assert_eq!(summary.duration_seconds, 1.0);
    }

    #[test]
    fn rejects_crc_corruption() {
        let mut bytes = synthetic_ogg();
        let last = bytes.len() - 1;
        bytes[last] ^= 0xff;
        let mut file = NamedTempFile::new().expect("temp output");
        file.write_all(&bytes).expect("write Ogg");
        file.as_file_mut().rewind().expect("rewind");
        assert!(validate_ogg_vorbis(file.as_file_mut()).is_err());
    }
}
