use std::path::PathBuf;

use clap::Parser;
use music_ai_mgg_helper::{
    decrypt_authorized_musicex, harden_process, DecryptOptions, HelperError,
};

#[derive(Debug, Parser)]
#[command(
    name = "music-ai-mgg-helper",
    version,
    about = "Convert an authorized MusicEx MGG to a validated local Ogg on macOS"
)]
struct Arguments {
    /// Confirm that the current QQ Music account is authorized to play this file.
    #[arg(long)]
    confirm_authorized_use: bool,

    /// New .ogg output path. Existing paths are never overwritten.
    #[arg(short, long, value_name = "OUTPUT")]
    output: PathBuf,

    /// MusicEx .mgg input file.
    #[arg(value_name = "INPUT")]
    input: PathBuf,
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let exit_code = match run().await {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("Error: {error}");
            1
        }
    };
    std::process::exit(exit_code);
}

async fn run() -> Result<(), HelperError> {
    harden_process()?;
    let arguments = Arguments::parse();
    let receipt = decrypt_authorized_musicex(DecryptOptions {
        input: &arguments.input,
        output: &arguments.output,
        confirm_authorized_use: arguments.confirm_authorized_use,
    })
    .await?;

    println!(
        "Created validated Ogg: {} ({} bytes, {} pages, {:.3}s)",
        receipt.output_path.display(),
        receipt.summary.bytes,
        receipt.summary.pages,
        receipt.summary.duration_seconds,
    );
    Ok(())
}
