use crate::error::HelperError;

pub fn harden_process() -> Result<(), HelperError> {
    #[cfg(not(target_os = "macos"))]
    {
        return Err(HelperError::UnsupportedPlatform);
    }

    #[cfg(target_os = "macos")]
    unsafe {
        if libc::geteuid() == 0 {
            return Err(HelperError::InvalidInput("refusing to run as root"));
        }

        libc::umask(0o077);
        let limit = libc::rlimit {
            rlim_cur: 0,
            rlim_max: 0,
        };
        if libc::setrlimit(libc::RLIMIT_CORE, &limit) != 0 {
            return Err(HelperError::Io("could not disable core dumps"));
        }
    }

    Ok(())
}
