use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

use crate::error::HelperError;

const MUSICEX_TRAILER_SIZE: u64 = 16;
const MAX_MUSICEX_FOOTER_SIZE: u64 = 16 * 1024;

#[derive(Debug)]
pub struct MusicexInfo {
    pub audio_len: u64,
    pub media_mid: String,
    pub api_filename: String,
}

pub fn read_musicex_info(
    file: &mut File,
    file_size: u64,
    input_path: &Path,
) -> Result<MusicexInfo, HelperError> {
    if file_size <= MUSICEX_TRAILER_SIZE {
        return Err(HelperError::InvalidMusicex("file is too small"));
    }

    file.seek(SeekFrom::End(-(MUSICEX_TRAILER_SIZE as i64)))
        .map_err(|_| HelperError::Io("could not read the MusicEx trailer"))?;
    let mut trailer = [0_u8; MUSICEX_TRAILER_SIZE as usize];
    file.read_exact(&mut trailer)
        .map_err(|_| HelperError::Io("could not read the MusicEx trailer"))?;

    if &trailer[8..] != b"musicex\0" {
        return Err(HelperError::InvalidMusicex("missing MusicEx marker"));
    }

    let footer_size = u32::from_le_bytes(
        trailer[0..4]
            .try_into()
            .map_err(|_| HelperError::InvalidMusicex("invalid footer size"))?,
    ) as u64;
    let version = u32::from_le_bytes(
        trailer[4..8]
            .try_into()
            .map_err(|_| HelperError::InvalidMusicex("invalid footer version"))?,
    );

    if version != 1 {
        return Err(HelperError::InvalidMusicex("unsupported MusicEx version"));
    }
    if !(MUSICEX_TRAILER_SIZE..=MAX_MUSICEX_FOOTER_SIZE).contains(&footer_size)
        || footer_size >= file_size
    {
        return Err(HelperError::InvalidMusicex("footer size is out of bounds"));
    }

    file.seek(SeekFrom::Start(file_size - footer_size))
        .map_err(|_| HelperError::Io("could not read MusicEx metadata"))?;
    let metadata_len = usize::try_from(footer_size - MUSICEX_TRAILER_SIZE)
        .map_err(|_| HelperError::InvalidMusicex("footer is too large"))?;
    let mut metadata = vec![0_u8; metadata_len];
    file.read_exact(&mut metadata)
        .map_err(|_| HelperError::Io("could not read MusicEx metadata"))?;

    let media_mid = read_utf16_le(&metadata, 0x0c, 60)?;
    let footer_filename = read_utf16_le(&metadata, 0x48, 68)?;
    validate_media_mid(&media_mid)?;
    let api_filename = normalize_api_filename(&footer_filename, input_path)?;

    Ok(MusicexInfo {
        audio_len: file_size - footer_size,
        media_mid,
        api_filename,
    })
}

fn read_utf16_le(data: &[u8], offset: usize, maximum_bytes: usize) -> Result<String, HelperError> {
    if offset >= data.len() {
        return Err(HelperError::InvalidMusicex("metadata field is missing"));
    }

    let mut units = Vec::new();
    let end = data.len().min(offset.saturating_add(maximum_bytes));
    let mut cursor = offset;
    while cursor + 1 < end {
        let unit = u16::from_le_bytes([data[cursor], data[cursor + 1]]);
        if unit == 0 {
            break;
        }
        units.push(unit);
        cursor += 2;
    }
    String::from_utf16(&units)
        .map_err(|_| HelperError::InvalidMusicex("metadata is not valid UTF-16"))
}

fn validate_media_mid(value: &str) -> Result<(), HelperError> {
    if value.is_empty()
        || value.len() > 64
        || !value.bytes().all(|byte| byte.is_ascii_alphanumeric())
    {
        return Err(HelperError::InvalidMusicex("media identifier is invalid"));
    }
    Ok(())
}

fn normalize_api_filename(value: &str, input_path: &Path) -> Result<String, HelperError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return Err(HelperError::InvalidMusicex("media filename is invalid"));
    }

    let lower = value.to_ascii_lowercase();
    if [".mgg", ".mgg0", ".mgg1", ".mggl"]
        .iter()
        .any(|extension| lower.ends_with(extension))
    {
        return Ok(value.to_owned());
    }

    let extension = input_path
        .extension()
        .and_then(|extension| extension.to_str())
        .ok_or(HelperError::InvalidInput(
            "input must have an MGG extension",
        ))?
        .to_ascii_lowercase();
    if !matches!(extension.as_str(), "mgg" | "mgg0" | "mgg1" | "mggl") {
        return Err(HelperError::InvalidInput(
            "input must have an MGG extension",
        ));
    }
    Ok(format!("{value}.{extension}"))
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use tempfile::NamedTempFile;

    use super::*;

    fn utf16_field(target: &mut [u8], offset: usize, value: &str) {
        for (index, unit) in value.encode_utf16().enumerate() {
            let bytes = unit.to_le_bytes();
            target[offset + index * 2..offset + index * 2 + 2].copy_from_slice(&bytes);
        }
    }

    fn musicex_footer() -> Vec<u8> {
        let mut metadata = vec![0_u8; 176];
        utf16_field(&mut metadata, 0x0c, "001122AABBcc");
        utf16_field(&mut metadata, 0x48, "O4M000fixture");
        let footer_size = (metadata.len() + MUSICEX_TRAILER_SIZE as usize) as u32;
        metadata.extend_from_slice(&footer_size.to_le_bytes());
        metadata.extend_from_slice(&1_u32.to_le_bytes());
        metadata.extend_from_slice(b"musicex\0");
        metadata
    }

    #[test]
    fn parses_bounded_musicex_footer() {
        let mut input = NamedTempFile::new().expect("temp input");
        input.write_all(&[0xaa; 1024]).expect("audio");
        input.write_all(&musicex_footer()).expect("footer");
        input.flush().expect("flush");
        let size = input.as_file().metadata().expect("metadata").len();
        let info = read_musicex_info(input.as_file_mut(), size, Path::new("fixture.mgg"))
            .expect("valid footer");
        assert_eq!(info.audio_len, 1024);
        assert_eq!(info.media_mid, "001122AABBcc");
        assert_eq!(info.api_filename, "O4M000fixture.mgg");
    }

    #[test]
    fn rejects_oversized_footer() {
        let mut input = NamedTempFile::new().expect("temp input");
        input.write_all(&[0xaa; 1024]).expect("audio");
        let mut footer = musicex_footer();
        let start = footer.len() - 16;
        footer[start..start + 4].copy_from_slice(&20_000_u32.to_le_bytes());
        input.write_all(&footer).expect("footer");
        input.flush().expect("flush");
        let size = input.as_file().metadata().expect("metadata").len();
        assert!(read_musicex_info(input.as_file_mut(), size, Path::new("fixture.mgg")).is_err());
    }
}
