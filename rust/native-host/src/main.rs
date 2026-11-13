use automated_apply_native::{Failure, error_frame, run, write_frame};
fn main() {
    let args: Vec<_> = std::env::args_os().collect();
    let value = match (args.get(1), args.get(2).and_then(|v| v.to_str())) {
        (Some(path), Some(origin)) => run(std::path::Path::new(path), origin),
        _ => error_frame(Failure("native_configuration_error"), None),
    };
    let _ = write_frame(&mut std::io::stdout().lock(), &value);
}
