use automated_apply_domain::matching::{Company, Listing, Profile, base_match, discovery_match};
use serde::Deserialize;
use serde_json::Value;
use std::{
    io::{Read, Write},
    time::Instant,
};
#[derive(Deserialize)]
struct Case {
    job: Listing,
    profile: Profile,
    company: Option<Company>,
    #[serde(default)]
    history_match: bool,
}
fn evaluate(c: &Case) -> Value {
    serde_json::json!({"base":base_match(&c.job,&c.profile),"discovery":discovery_match(&c.job,&c.profile,c.company.as_ref(),c.history_match)})
}
fn cpu_ms() -> f64 {
    let mut time = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: time points to a valid writable timespec for the duration of clock_gettime.
    assert_eq!(
        unsafe { libc::clock_gettime(libc::CLOCK_PROCESS_CPUTIME_ID, &mut time) },
        0,
        "process_cpu_clock_unavailable"
    );
    time.tv_sec as f64 * 1000.0 + time.tv_nsec as f64 / 1000000.0
}
fn main() {
    let mut bytes = Vec::new();
    if std::io::stdin()
        .take(4 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .is_err()
        || bytes.len() > 4 * 1024 * 1024
    {
        std::process::exit(2);
    }
    let cases: Vec<Case> = match serde_json::from_slice(&bytes) {
        Ok(cases) => cases,
        Err(_) => std::process::exit(2),
    };
    let output = if std::env::args().any(|arg| arg == "--benchmark") {
        for case in &cases {
            std::hint::black_box(evaluate(case));
        }
        let mut samples = vec![];
        for _ in 0..5 {
            let wall = Instant::now();
            let cpu = cpu_ms();
            for case in &cases {
                std::hint::black_box(evaluate(case));
            }
            samples.push(serde_json::json!({"wall_ms":wall.elapsed().as_secs_f64()*1000.0,"cpu_ms":cpu_ms()-cpu}));
        }
        serde_json::json!({"samples":samples,"cases_per_sample":cases.len(),"scope":"warm base+discovery calculation and output projection; input validation and process startup excluded"})
    } else {
        serde_json::to_value(cases.iter().map(evaluate).collect::<Vec<_>>()).unwrap()
    };
    if let Ok(bytes) = serde_json::to_vec(&output) {
        let _ = std::io::stdout().write_all(&bytes);
    }
}
