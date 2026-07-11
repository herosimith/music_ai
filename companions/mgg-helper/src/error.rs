use std::fmt::{Display, Formatter};

#[derive(Debug)]
pub enum HelperError {
    AuthorizationRequired,
    UnsupportedPlatform,
    InvalidInput(&'static str),
    InvalidMusicex(&'static str),
    Credentials(&'static str),
    Network(&'static str),
    ApiStatus(u16),
    ApiCode(i64),
    KeyUnavailable(i64),
    InvalidResponse(&'static str),
    Crypto(String),
    InvalidOgg(&'static str),
    Io(&'static str),
    Output(&'static str),
}

impl Display for HelperError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::AuthorizationRequired => write!(
                formatter,
                "explicit authorized-use confirmation is required"
            ),
            Self::UnsupportedPlatform => write!(formatter, "this helper supports macOS only"),
            Self::InvalidInput(message) => write!(formatter, "invalid input: {message}"),
            Self::InvalidMusicex(message) => {
                write!(formatter, "invalid MusicEx container: {message}")
            }
            Self::Credentials(message) => {
                write!(formatter, "QQ Music credentials are unavailable: {message}")
            }
            Self::Network(message) => write!(formatter, "QQ Music request failed: {message}"),
            Self::ApiStatus(status) => {
                write!(formatter, "QQ Music returned HTTP status {status}")
            }
            Self::ApiCode(code) => write!(formatter, "QQ Music rejected the request ({code})"),
            Self::KeyUnavailable(code) => {
                write!(
                    formatter,
                    "no key was returned for this authorized account ({code})"
                )
            }
            Self::InvalidResponse(message) => {
                write!(
                    formatter,
                    "QQ Music returned an invalid response: {message}"
                )
            }
            Self::Crypto(message) => write!(formatter, "QMC2 key setup failed: {message}"),
            Self::InvalidOgg(message) => write!(formatter, "decrypted Ogg is invalid: {message}"),
            Self::Io(message) => write!(formatter, "file operation failed: {message}"),
            Self::Output(message) => write!(formatter, "output was not created: {message}"),
        }
    }
}

impl std::error::Error for HelperError {}

impl From<crate::qmc2::Qmc2Error> for HelperError {
    fn from(error: crate::qmc2::Qmc2Error) -> Self {
        Self::Crypto(error.to_string())
    }
}
