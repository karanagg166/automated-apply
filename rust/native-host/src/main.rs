use automated_apply_native::{Failure, error_frame, run, write_frame};
use std::{ffi::OsString, path::PathBuf};
fn invocation(
    args: &[OsString],
    executable: impl FnOnce() -> std::io::Result<PathBuf>,
) -> Result<(PathBuf, &str), Failure> {
    let first = args.first().ok_or(Failure("native_configuration_error"))?;
    if let Some(origin) = first
        .to_str()
        .filter(|s| s.starts_with("chrome-extension://"))
    {
        // Browser manifests cannot supply configuration arguments. Direct launches
        // use one fixed adjacent private file; no cwd or ambient env lookup.
        let path = executable()
            .map_err(|_| Failure("native_configuration_error"))?
            .with_file_name("automated-apply-native.private.env");
        return Ok((path, origin));
    }
    let origin = args
        .get(1)
        .and_then(|v| v.to_str())
        .ok_or(Failure("native_configuration_error"))?;
    Ok((PathBuf::from(first), origin))
}
fn main() {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    let value = match invocation(&args, std::env::current_exe) {
        Ok((path, origin)) => run(&path, origin),
        Err(error) => error_frame(error, None),
    };
    let _ = write_frame(&mut std::io::stdout().lock(), &value);
}
#[cfg(test)]
mod tests {
    use super::*;
    const ORIGIN: &str = "chrome-extension://gdjbmkffcpicbpiikcohlmokkmcpipgp/";
    #[test]
    fn direct_browser_launch_uses_only_the_executable_adjacent_private_file() {
        let args = vec![OsString::from(ORIGIN)];
        let (path, origin) = invocation(&args, || {
            Ok(PathBuf::from("/owned/release/automated-apply-native"))
        })
        .unwrap();
        assert_eq!(
            path,
            PathBuf::from("/owned/release/automated-apply-native.private.env")
        );
        assert_eq!(origin, ORIGIN);
        assert!(invocation(&args, || Err(std::io::Error::other("fixture"))).is_err());
        assert!(invocation(&[], || panic!("executable must not be read")).is_err());
    }
    #[test]
    fn existing_explicit_configuration_does_not_consult_executable_or_environment() {
        let args = vec![OsString::from("/owned/host.env"), OsString::from(ORIGIN)];
        let (path, origin) = invocation(&args, || {
            panic!("explicit invocation must not resolve sibling configuration")
        })
        .unwrap();
        assert_eq!(path, PathBuf::from("/owned/host.env"));
        assert_eq!(origin, ORIGIN);
    }
}
