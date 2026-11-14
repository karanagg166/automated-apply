use automated_apply_documents::{MAX_BYTES, Mode, inspect};
use std::io::{Read, Write};
fn run() -> Result<(), &'static str> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let mode = match arguments.as_slice() {
        [value] if value == "extract" => Mode::Extract,
        [value] if value == "validate" => Mode::Validate,
        _ => return Err("invalid_document_worker_mode"),
    };
    // Parent additionally supervises elapsed time, output size and macOS RSS.
    unsafe {
        let cpu = libc::rlimit {
            rlim_cur: 5,
            rlim_max: 5,
        };
        if libc::setrlimit(libc::RLIMIT_CPU, &cpu) != 0 {
            return Err("document_limits_unavailable");
        }
        #[cfg(target_os = "linux")]
        {
            let memory = libc::rlimit {
                rlim_cur: 768 * 1024 * 1024,
                rlim_max: 768 * 1024 * 1024,
            };
            if libc::setrlimit(libc::RLIMIT_AS, &memory) != 0 {
                return Err("document_limits_unavailable");
            }
        }
    }
    let mut raw = Vec::new();
    std::io::stdin()
        .take((MAX_BYTES + 1) as u64)
        .read_to_end(&mut raw)
        .map_err(|_| "document_input_failed")?;
    let extracted = inspect(&raw, mode)?;
    match mode {
        Mode::Validate => std::io::stdout()
            .write_all(b"valid")
            .map_err(|_| "document_output_failed")?,
        Mode::Extract => serde_json::to_writer(std::io::stdout(), &extracted)
            .map_err(|_| "document_output_failed")?,
    }
    Ok(())
}
fn main() -> std::process::ExitCode {
    match run() {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(code) => {
            eprintln!("{code}");
            std::process::ExitCode::FAILURE
        }
    }
}
