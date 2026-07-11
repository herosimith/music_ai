use std::fs::{File, OpenOptions};
use std::io::Cursor;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::time::Duration;

use plist::Value;
use serde::{Deserialize, Serialize};
use zeroize::Zeroizing;

use crate::error::HelperError;
use crate::musicex::MusicexInfo;

const ENDPOINT: &str = "https://u.y.qq.com/cgi-bin/musicu.fcg";
const MAX_PREFERENCES_BYTES: u64 = 5 * 1024 * 1024;
const MAX_RESPONSE_BYTES: usize = 1024 * 1024;

pub struct QQMusicCredentials {
    uin: Zeroizing<String>,
    authst: Zeroizing<String>,
}

#[derive(Serialize)]
struct MusicuRequest<'a> {
    comm: MusicuComm<'a>,
    #[serde(rename = "req_1")]
    request: MusicuRequestItem<'a>,
}

#[derive(Serialize)]
struct MusicuComm<'a> {
    authst: &'a str,
    ct: &'static str,
    cv: &'static str,
    uin: &'a str,
    #[serde(rename = "tmeLoginType")]
    login_type: &'static str,
}

#[derive(Serialize)]
struct MusicuRequestItem<'a> {
    module: &'static str,
    method: &'static str,
    param: MusicuParam<'a>,
}

#[derive(Serialize)]
struct MusicuParam<'a> {
    filename: [&'a str; 1],
    guid: &'static str,
    songmid: [&'a str; 1],
    songtype: [i32; 1],
    uin: &'a str,
    loginflag: i32,
    platform: &'static str,
    ctx: i32,
}

#[derive(Deserialize)]
struct MusicuResponse {
    #[serde(rename = "req_1")]
    request: Option<MusicuResponseItem>,
}

#[derive(Deserialize)]
struct MusicuResponseItem {
    code: Option<i64>,
    data: Option<MusicuData>,
}

#[derive(Deserialize)]
struct MusicuData {
    midurlinfo: Option<Vec<MidUrlInfo>>,
}

#[derive(Deserialize)]
struct MidUrlInfo {
    ekey: Option<String>,
    result: Option<i64>,
}

pub fn read_credentials() -> Result<QQMusicCredentials, HelperError> {
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .ok_or(HelperError::Credentials("home directory is unavailable"))?;
    let candidates = [
        home.join(
            "Library/Containers/com.tencent.QQMusicMac/Data/Library/Preferences/com.tencent.QQMusicMac.plist",
        ),
        home.join("Library/Preferences/com.tencent.QQMusicMac.plist"),
    ];

    let mut preferences = None;
    for candidate in candidates {
        match open_owned_regular_file(&candidate) {
            Ok(file) => {
                preferences = Some(file);
                break;
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
            Err(_) => {
                return Err(HelperError::Credentials(
                    "preferences file is not safe to read",
                ))
            }
        }
    }
    let preferences = preferences.ok_or(HelperError::Credentials(
        "QQ Music is not installed or has no local login",
    ))?;
    let value = Value::from_reader(preferences)
        .map_err(|_| HelperError::Credentials("preferences file is invalid"))?;
    let dictionary = value.as_dictionary().ok_or(HelperError::Credentials(
        "preferences file has an invalid shape",
    ))?;
    let archive = dictionary
        .get("AutoLoginUserInfo")
        .and_then(Value::as_data)
        .ok_or(HelperError::Credentials(
            "QQ Music is not currently logged in",
        ))?;
    parse_archived_credentials(archive)
}

fn open_owned_regular_file(path: &Path) -> Result<File, std::io::Error> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.file_type().is_file()
        || metadata.len() > MAX_PREFERENCES_BYTES
        || metadata.uid() != unsafe { libc::geteuid() }
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "unsafe preferences file",
        ));
    }
    Ok(file)
}

fn parse_archived_credentials(data: &[u8]) -> Result<QQMusicCredentials, HelperError> {
    let value = Value::from_reader(Cursor::new(data))
        .map_err(|_| HelperError::Credentials("login archive is invalid"))?;
    let dictionary = value.as_dictionary().ok_or(HelperError::Credentials(
        "login archive has an invalid shape",
    ))?;
    let objects =
        dictionary
            .get("$objects")
            .and_then(Value::as_array)
            .ok_or(HelperError::Credentials(
                "login archive has no object table",
            ))?;

    fn resolve(objects: &[Value], value: &Value) -> Option<String> {
        let Value::Uid(uid) = value else {
            return None;
        };
        objects
            .get(uid.get() as usize)
            .and_then(Value::as_string)
            .map(ToOwned::to_owned)
    }

    for object in objects {
        let Some(fields) = object.as_dictionary() else {
            continue;
        };
        let Some(auth_value) = fields.get("strAuthst") else {
            continue;
        };
        let authst = resolve(objects, auth_value)
            .ok_or(HelperError::Credentials("login archive has no auth key"))?;
        let uin = fields
            .get("strUserAccount")
            .and_then(|value| resolve(objects, value))
            .or_else(|| {
                fields
                    .get("nCurrUseId")
                    .and_then(Value::as_unsigned_integer)
                    .map(|value| value.to_string())
            })
            .ok_or(HelperError::Credentials(
                "login archive has no account identifier",
            ))?;

        if authst.is_empty()
            || authst.len() > 4096
            || authst.chars().any(char::is_control)
            || uin.is_empty()
            || uin.len() > 64
            || !uin.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Err(HelperError::Credentials("login values failed validation"));
        }
        return Ok(QQMusicCredentials {
            uin: Zeroizing::new(uin),
            authst: Zeroizing::new(authst),
        });
    }

    Err(HelperError::Credentials(
        "login archive has no active account",
    ))
}

pub async fn fetch_ekey(
    credentials: &QQMusicCredentials,
    musicex: &MusicexInfo,
) -> Result<Zeroizing<String>, HelperError> {
    let request = MusicuRequest {
        comm: MusicuComm {
            authst: credentials.authst.as_str(),
            ct: "19",
            cv: "1859",
            uin: credentials.uin.as_str(),
            login_type: "3",
        },
        request: MusicuRequestItem {
            module: "music.vkey.GetEVkey",
            method: "CgiGetEVkey",
            param: MusicuParam {
                filename: [&musicex.api_filename],
                guid: "10000",
                songmid: [&musicex.media_mid],
                songtype: [1],
                uin: credentials.uin.as_str(),
                loginflag: 1,
                platform: "20",
                ctx: 1,
            },
        },
    };
    let request_body = Zeroizing::new(
        serde_json::to_vec(&request)
            .map_err(|_| HelperError::InvalidResponse("request could not be encoded"))?,
    );

    let client = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(10))
        .build()
        .map_err(|_| HelperError::Network("secure HTTP client could not be initialized"))?;
    let mut response = client
        .post(ENDPOINT)
        .header("Content-Type", "application/json")
        .header(
            "User-Agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        )
        .header("Referer", "https://y.qq.com/")
        .body(request_body.as_slice().to_owned())
        .send()
        .await
        .map_err(|_| HelperError::Network("HTTPS request did not complete"))?;

    let status = response.status();
    if !status.is_success() {
        return Err(HelperError::ApiStatus(status.as_u16()));
    }
    if response
        .content_length()
        .is_some_and(|length| length > MAX_RESPONSE_BYTES as u64)
    {
        return Err(HelperError::InvalidResponse("response exceeds 1 MiB"));
    }

    let mut response_body = Zeroizing::new(Vec::new());
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| HelperError::Network("HTTPS response was interrupted"))?
    {
        if response_body.len().saturating_add(chunk.len()) > MAX_RESPONSE_BYTES {
            return Err(HelperError::InvalidResponse("response exceeds 1 MiB"));
        }
        response_body.extend_from_slice(&chunk);
    }
    parse_ekey_response(&response_body)
}

fn parse_ekey_response(body: &[u8]) -> Result<Zeroizing<String>, HelperError> {
    let mut response: MusicuResponse = serde_json::from_slice(body)
        .map_err(|_| HelperError::InvalidResponse("response is not valid JSON"))?;
    let request = response
        .request
        .as_mut()
        .ok_or(HelperError::InvalidResponse("response is missing req_1"))?;
    let code = request.code.unwrap_or(-1);
    if code != 0 {
        return Err(HelperError::ApiCode(code));
    }
    let item = request
        .data
        .as_mut()
        .and_then(|data| data.midurlinfo.as_mut())
        .and_then(|items| items.first_mut())
        .ok_or(HelperError::InvalidResponse("response has no key result"))?;
    let result_code = item.result.unwrap_or(-1);
    if result_code != 0 {
        return Err(HelperError::KeyUnavailable(result_code));
    }
    let ekey = item
        .ekey
        .take()
        .filter(|value| !value.is_empty())
        .ok_or(HelperError::KeyUnavailable(0))?;
    if ekey.len() > 16 * 1024
        || !ekey
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'+' | b'/' | b'='))
    {
        return Err(HelperError::InvalidResponse("key encoding is invalid"));
    }
    Ok(Zeroizing::new(ekey))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_key_without_exposing_other_response_fields() {
        let response = br#"{
            "req_1": {
                "code": 0,
                "data": {"midurlinfo": [{"result": 0, "ekey": "QUJDREVGR0g="}]}
            }
        }"#;
        let key = parse_ekey_response(response).expect("valid response");
        assert_eq!(key.as_str(), "QUJDREVGR0g=");
    }

    #[test]
    fn rejects_empty_or_malformed_keys() {
        let empty = br#"{"req_1":{"code":0,"data":{"midurlinfo":[{"result":0,"ekey":""}]}}}"#;
        assert!(parse_ekey_response(empty).is_err());

        let malformed =
            br#"{"req_1":{"code":0,"data":{"midurlinfo":[{"result":0,"ekey":"not a key!"}]}}}"#;
        assert!(parse_ekey_response(malformed).is_err());
    }
}
