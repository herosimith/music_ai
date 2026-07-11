mod error;
mod musicex;
mod ogg;
mod process;
mod qmc2;
mod qqmusic;
mod secure_io;

use std::path::{Path, PathBuf};

pub use error::HelperError;
pub use ogg::OggSummary;
pub use process::harden_process;

use musicex::read_musicex_info;
use qmc2::Qmc2Crypto;
use qqmusic::{fetch_ekey, read_credentials};
use secure_io::{decrypt_to_atomic_output, open_regular_input};

pub struct DecryptOptions<'a> {
    pub input: &'a Path,
    pub output: &'a Path,
    pub confirm_authorized_use: bool,
}

#[derive(Debug)]
pub struct DecryptReceipt {
    pub output_path: PathBuf,
    pub summary: OggSummary,
}

pub async fn decrypt_authorized_musicex(
    options: DecryptOptions<'_>,
) -> Result<DecryptReceipt, HelperError> {
    if !options.confirm_authorized_use {
        return Err(HelperError::AuthorizationRequired);
    }

    let mut input = open_regular_input(options.input)?;
    let musicex = read_musicex_info(&mut input.file, input.size, options.input)?;
    let credentials = read_credentials()?;
    let ekey = fetch_ekey(&credentials, &musicex).await?;
    drop(credentials);
    let crypto = Qmc2Crypto::from_ekey(ekey.as_str())?;
    drop(ekey);

    let (output_path, summary) = decrypt_to_atomic_output(
        &mut input.file,
        &input.canonical_path,
        musicex.audio_len,
        options.output,
        &crypto,
    )?;
    Ok(DecryptReceipt {
        output_path,
        summary,
    })
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::os::unix::fs::PermissionsExt;

    use base64::Engine;
    use tempfile::tempdir;
    use zeroize::Zeroizing;

    use super::*;

    fn utf16_field(target: &mut [u8], offset: usize, value: &str) {
        for (index, unit) in value.encode_utf16().enumerate() {
            target[offset + index * 2..offset + index * 2 + 2].copy_from_slice(&unit.to_le_bytes());
        }
    }

    fn append_musicex_footer(audio: &mut Vec<u8>) {
        let mut metadata = vec![0_u8; 176];
        utf16_field(&mut metadata, 0x0c, "001122AABBcc");
        utf16_field(&mut metadata, 0x48, "O4M000fixture.mgg");
        let footer_size = (metadata.len() + 16) as u32;
        audio.extend_from_slice(&metadata);
        audio.extend_from_slice(&footer_size.to_le_bytes());
        audio.extend_from_slice(&1_u32.to_le_bytes());
        audio.extend_from_slice(b"musicex\0");
    }

    #[test]
    fn synthetic_musicex_decrypts_to_validated_atomic_ogg() {
        let directory = tempdir().expect("temp directory");
        let input_path = directory.path().join("fixture.mgg");
        let output_path = directory.path().join("fixture.ogg");
        let expected = crate::ogg::synthetic_ogg();
        let raw_key = b"This is a test key for test purpose :D";
        let ekey = Zeroizing::new(base64::engine::general_purpose::STANDARD.encode(raw_key));
        let crypto = Qmc2Crypto::from_ekey(ekey.as_str()).expect("test crypto");
        let mut encrypted = expected.clone();
        crypto.decrypt(0, &mut encrypted);
        append_musicex_footer(&mut encrypted);
        fs::write(&input_path, encrypted).expect("encrypted fixture");

        let mut input = open_regular_input(&input_path).expect("secure input");
        let musicex =
            read_musicex_info(&mut input.file, input.size, &input_path).expect("MusicEx footer");
        let decryptor = Qmc2Crypto::from_ekey(ekey.as_str()).expect("test decryptor");
        let (created, summary) = decrypt_to_atomic_output(
            &mut input.file,
            &input.canonical_path,
            musicex.audio_len,
            &output_path,
            &decryptor,
        )
        .expect("validated decrypt");

        assert_eq!(
            created,
            fs::canonicalize(directory.path())
                .expect("canonical temp directory")
                .join("fixture.ogg")
        );
        assert_eq!(fs::read(&output_path).expect("output"), expected);
        assert_eq!(summary.sample_rate, 44_100);
        assert_eq!(summary.channels, 2);
        assert_eq!(
            fs::metadata(&output_path)
                .expect("output metadata")
                .permissions()
                .mode()
                & 0o777,
            0o600
        );

        let duplicate = decrypt_to_atomic_output(
            &mut input.file,
            &input.canonical_path,
            musicex.audio_len,
            &output_path,
            &decryptor,
        );
        assert!(duplicate.is_err());
    }
}
