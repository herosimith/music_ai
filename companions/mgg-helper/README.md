# music-ai-mgg-helper

This is an optional, independently built macOS companion for converting a
MusicEx `.mgg` file that the current QQ Music account is authorized to play into
a validated Ogg Vorbis file. It is GPL-3.0-only software derived from
`ownlight6/qmc-decoder` v1.2.0; it is not linked into the music_ai web or server
applications.

The helper reads QQ Music's local `AutoLoginUserInfo` only after the explicit
`--confirm-authorized-use` flag is supplied. It makes one bounded HTTPS request
to `https://u.y.qq.com/cgi-bin/musicu.fcg`, does not use proxies or redirects,
and never prints or stores the UIN, `authst`, eKey, response body, Media MID, or
internal media filename. The encrypted input and key processing stay on the
Mac. The resulting Ogg is imported into music_ai as an ordinary local audio
file.

## Build

Requires the Rust toolchain on macOS:

```bash
cd companions/mgg-helper
cargo build --release --locked
```

## Convert

Close any untrusted terminal log capture before running. The output path must
not already exist.

```bash
./target/release/music-ai-mgg-helper \
  --confirm-authorized-use \
  --output "$HOME/Desktop/song.ogg" \
  "$HOME/Music/song.mgg"
```

The command fails closed unless the input is a regular, non-symlink MusicEx
MGG, the account returns a non-empty eKey, and the complete output passes Ogg
page, CRC, sequence, BOS/EOS, and Vorbis-header validation. Partial output is
removed automatically. Windows process-memory credential discovery, batch
conversion, GUI mode, QMC1, and manually supplied keys are intentionally not
included.

This tool does not grant playback rights. Use it only for audio your account is
authorized to access and only where permitted by applicable law and service
terms. The repository's license boundary is an engineering design, not legal
advice.
