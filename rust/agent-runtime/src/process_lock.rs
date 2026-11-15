//! The same kernel-held execution lease as the legacy worker. Never unlink a lock inode.
use crate::{Failure, Result, configuration::Configuration};
use std::{
    ffi::CStr,
    fs::{DirBuilder, File},
    os::{
        fd::AsRawFd,
        unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt},
    },
    path::{Path, PathBuf},
};

pub struct ProcessLock {
    _file: File,
}
impl ProcessLock {
    pub fn acquire(config: &Configuration, fixture_directory: Option<&Path>) -> Result<Self> {
        Self::acquire_service(config, fixture_directory, "execution")
    }
    pub fn acquire_telegram(
        config: &Configuration,
        fixture_directory: Option<&Path>,
    ) -> Result<Self> {
        Self::acquire_service(config, fixture_directory, "telegram")
    }
    pub fn acquire_writer(
        config: &Configuration,
        fixture_directory: Option<&Path>,
    ) -> Result<Self> {
        Self::acquire_service(config, fixture_directory, "writer")
    }
    fn acquire_service(
        config: &Configuration,
        fixture_directory: Option<&Path>,
        service: &str,
    ) -> Result<Self> {
        let directory = if config.fixture {
            fixture_directory
                .filter(|p| p.is_absolute())
                .ok_or(Failure("private_fixture_lock_directory_required"))?
                .to_path_buf()
        } else {
            if fixture_directory.is_some() {
                return Err(Failure("production_lock_override_forbidden"));
            }
            if cfg!(target_os = "macos") {
                owner_home()?.join("Library/Application Support/Automated Apply/runtime-locks")
            } else {
                // Same path as the Python launcher; writable under a read-only image
                // with /tmp mounted. Container replicas must share this lock directory.
                PathBuf::from(format!("/tmp/automated-apply-{}-runtime-locks", unsafe {
                    libc::geteuid()
                }))
            }
        };
        DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(&directory)
            .map_err(|_| Failure("private_worker_lock_required"))?;
        let meta = directory
            .symlink_metadata()
            .map_err(|_| Failure("private_worker_lock_required"))?;
        // SAFETY: geteuid has no preconditions.
        if !meta.is_dir() || meta.uid() != unsafe { libc::geteuid() } || meta.mode() & 0o077 != 0 {
            return Err(Failure("private_worker_lock_required"));
        }
        let path = directory.join(format!("{service}-{}.lock", config.target_identity));
        let file = File::options()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
            .open(path)
            .map_err(|_| Failure("private_worker_lock_required"))?;
        let meta = file
            .metadata()
            .map_err(|_| Failure("private_worker_lock_required"))?;
        // SAFETY: geteuid has no preconditions; the descriptor is a live owned file.
        if !meta.is_file() || meta.uid() != unsafe { libc::geteuid() } || meta.mode() & 0o077 != 0 {
            return Err(Failure("private_worker_lock_required"));
        }
        // SAFETY: flock receives the valid descriptor and documented operation flags.
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err(Failure(match service {
                "telegram" => "telegram_worker_already_running",
                "writer" => "legacy_writer_already_running",
                _ => "execution_worker_already_running",
            }));
        }
        Ok(Self { _file: file })
    }
}
fn owner_home() -> Result<PathBuf> {
    let mut buffer = vec![0u8; 16384];
    loop {
        let mut entry = std::mem::MaybeUninit::<libc::passwd>::uninit();
        let mut found = std::ptr::null_mut();
        // SAFETY: entry/output/buffer point to writable allocations of the given sizes.
        let code = unsafe {
            libc::getpwuid_r(
                libc::geteuid(),
                entry.as_mut_ptr(),
                buffer.as_mut_ptr().cast(),
                buffer.len(),
                &mut found,
            )
        };
        if code == libc::ERANGE && buffer.len() < 1_048_576 {
            buffer.resize(buffer.len() * 2, 0);
            continue;
        }
        if code != 0 || found.is_null() {
            return Err(Failure("owner_home_unavailable"));
        }
        // SAFETY: successful getpwuid_r initialized entry and returns a NUL-terminated
        // directory inside buffer; it is copied before the buffer is dropped.
        let entry = unsafe { entry.assume_init() };
        if entry.pw_dir.is_null() {
            return Err(Failure("owner_home_unavailable"));
        }
        let directory = unsafe { CStr::from_ptr(entry.pw_dir) }
            .to_str()
            .map_err(|_| Failure("owner_home_unavailable"))?;
        let path = PathBuf::from(directory);
        if !path.is_absolute() {
            return Err(Failure("owner_home_unavailable"));
        }
        return Ok(path);
    }
}
