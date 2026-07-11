use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

use tempfile::Builder;
use zeroize::{Zeroize, Zeroizing};

use crate::error::HelperError;
use crate::ogg::{validate_ogg_vorbis, OggSummary};
use crate::qmc2::Qmc2Crypto;

pub const MAX_INPUT_BYTES: u64 = 500_000_000;
const CHUNK_BYTES: usize = 64 * 1024;

pub struct OpenInput {
    pub file: File,
    pub size: u64,
    pub canonical_path: PathBuf,
}

pub fn open_regular_input(path: &Path) -> Result<OpenInput, HelperError> {
    let extension = path
        .extension()
        .and_then(|extension| extension.to_str())
        .map(str::to_ascii_lowercase)
        .ok_or(HelperError::InvalidInput(
            "input must have an MGG extension",
        ))?;
    if !matches!(extension.as_str(), "mgg" | "mgg0" | "mgg1" | "mggl") {
        return Err(HelperError::InvalidInput(
            "input must have an MGG extension",
        ));
    }

    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)
        .map_err(|_| HelperError::InvalidInput("input cannot be opened safely"))?;
    let metadata = file
        .metadata()
        .map_err(|_| HelperError::InvalidInput("input metadata is unavailable"))?;
    if !metadata.file_type().is_file() {
        return Err(HelperError::InvalidInput("input is not a regular file"));
    }
    if metadata.len() == 0 || metadata.len() > MAX_INPUT_BYTES {
        return Err(HelperError::InvalidInput(
            "input size is outside the allowed range",
        ));
    }
    let canonical_path = fs::canonicalize(path)
        .map_err(|_| HelperError::InvalidInput("input path cannot be resolved"))?;

    Ok(OpenInput {
        file,
        size: metadata.len(),
        canonical_path,
    })
}

pub fn decrypt_to_atomic_output(
    input: &mut File,
    input_canonical_path: &Path,
    audio_len: u64,
    output: &Path,
    crypto: &Qmc2Crypto,
) -> Result<(PathBuf, OggSummary), HelperError> {
    if audio_len == 0 || audio_len > MAX_INPUT_BYTES {
        return Err(HelperError::InvalidInput("encrypted audio size is invalid"));
    }
    let output_path = safe_output_path(output)?;
    if output_path == input_canonical_path {
        return Err(HelperError::Output("input and output paths must differ"));
    }
    match fs::symlink_metadata(&output_path) {
        Ok(_) => return Err(HelperError::Output("output path already exists")),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err(HelperError::Output("output path cannot be inspected")),
    }

    let parent = output_path
        .parent()
        .ok_or(HelperError::Output("output directory is missing"))?;
    let mut temporary = Builder::new()
        .prefix(".music-ai-mgg-")
        .suffix(".ogg.tmp")
        .tempfile_in(parent)
        .map_err(|_| HelperError::Output("private temporary file could not be created"))?;
    temporary
        .as_file()
        .set_permissions(fs::Permissions::from_mode(0o600))
        .map_err(|_| HelperError::Output("temporary file permissions could not be restricted"))?;

    input
        .seek(SeekFrom::Start(0))
        .map_err(|_| HelperError::Io("input could not be rewound"))?;
    let mut buffer = Zeroizing::new(vec![0_u8; CHUNK_BYTES]);
    let mut offset = 0_u64;
    while offset < audio_len {
        let remaining = usize::try_from((audio_len - offset).min(CHUNK_BYTES as u64))
            .map_err(|_| HelperError::InvalidInput("input chunk size is invalid"))?;
        let read = input
            .read(&mut buffer[..remaining])
            .map_err(|_| HelperError::Io("encrypted audio could not be read"))?;
        if read == 0 {
            return Err(HelperError::Io("encrypted audio ended unexpectedly"));
        }
        crypto.decrypt(offset as usize, &mut buffer[..read]);
        temporary
            .write_all(&buffer[..read])
            .map_err(|_| HelperError::Output("temporary output could not be written"))?;
        buffer[..read].zeroize();
        offset += read as u64;
    }

    temporary
        .as_file_mut()
        .flush()
        .map_err(|_| HelperError::Output("temporary output could not be flushed"))?;
    temporary
        .as_file()
        .sync_all()
        .map_err(|_| HelperError::Output("temporary output could not be synchronized"))?;
    let summary = validate_ogg_vorbis(temporary.as_file_mut())?;
    if summary.bytes != audio_len {
        return Err(HelperError::InvalidOgg(
            "decrypted byte length does not match input",
        ));
    }

    temporary
        .persist_noclobber(&output_path)
        .map_err(|_| HelperError::Output("validated output could not be committed atomically"))?;
    if let Ok(directory) = File::open(parent) {
        let _ = directory.sync_all();
    }
    Ok((output_path, summary))
}

fn safe_output_path(path: &Path) -> Result<PathBuf, HelperError> {
    if !path
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("ogg"))
    {
        return Err(HelperError::Output("output must use the .ogg extension"));
    }
    let filename = path
        .file_name()
        .filter(|filename| !filename.is_empty())
        .ok_or(HelperError::Output("output filename is invalid"))?;
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let canonical_parent = fs::canonicalize(parent)
        .map_err(|_| HelperError::Output("output directory does not exist"))?;
    let metadata = canonical_parent
        .metadata()
        .map_err(|_| HelperError::Output("output directory cannot be inspected"))?;
    if !metadata.is_dir() {
        return Err(HelperError::Output("output parent is not a directory"));
    }
    Ok(canonical_parent.join(filename))
}

#[cfg(test)]
mod tests {
    use std::os::unix::fs::symlink;

    use tempfile::tempdir;

    use super::*;

    #[test]
    fn rejects_sparse_input_above_limit() {
        let directory = tempdir().expect("temp directory");
        let path = directory.path().join("oversized.mgg");
        let file = File::create(&path).expect("sparse file");
        file.set_len(MAX_INPUT_BYTES + 1)
            .expect("set sparse length");
        assert!(open_regular_input(&path).is_err());
    }

    #[test]
    fn rejects_input_symlink() {
        let directory = tempdir().expect("temp directory");
        let target = directory.path().join("target.mgg");
        fs::write(&target, [1_u8; 32]).expect("target file");
        let link = directory.path().join("link.mgg");
        symlink(&target, &link).expect("symlink");
        assert!(open_regular_input(&link).is_err());
    }

    #[test]
    fn normalizes_output_parent_and_rejects_non_ogg_extension() {
        let directory = tempdir().expect("temp directory");
        let existing = directory.path().join("existing.ogg");
        fs::write(&existing, []).expect("existing output");
        assert_eq!(
            safe_output_path(&existing).expect("safe shape"),
            fs::canonicalize(directory.path())
                .expect("canonical temp directory")
                .join("existing.ogg")
        );
        assert!(safe_output_path(&directory.path().join("output.mp3")).is_err());
    }
}
