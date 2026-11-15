//! Explicit one-request public probe. No runtime configuration, database or candidate data.
use automated_apply_agents::public_discovery::{self, Platform};
use serde_json::json;

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    if arguments.len() != 2
        || !matches!(arguments[0].as_str(), "--live-public-feed" | "--saved-rss")
    {
        eprintln!(
            "usage: public_feed_probe --live-public-feed himalayas|we_work_remotely OR --saved-rss PATH"
        );
        std::process::exit(2);
    }
    let saved = arguments[0] == "--saved-rss";
    let platform = match Platform::parse(if saved {
        "we_work_remotely"
    } else {
        &arguments[1]
    }) {
        Ok(platform) => platform,
        Err(error) => {
            eprintln!("{}", error.0);
            std::process::exit(2);
        }
    };
    let started = std::time::Instant::now();
    let result = if saved {
        use std::io::Read;
        let mut bytes = Vec::new();
        match std::fs::File::open(&arguments[1])
            .and_then(|file| file.take(4 * 1024 * 1024 + 1).read_to_end(&mut bytes))
        {
            Ok(_) => public_discovery::we_work_remotely(&bytes),
            Err(_) => Err(automated_apply_agents::Failure("saved_feed_unavailable")),
        }
    } else {
        public_discovery::fetch(platform).await
    };
    let requests = usize::from(!saved);
    match result {
        Ok(batch) => println!(
            "{}",
            json!({"platform":platform,"status":"PASS","jobs":batch.jobs.len(),
                "duplicates":batch.duplicate_count,"skipped_invalid":batch.skipped_invalid,
                "has_more":batch.has_more,"elapsed_ms":started.elapsed().as_millis(),
                "truncated_previews":batch.jobs.iter().filter(|job|job.description_truncated).count(),
                "requests":requests,"candidate_data_sent":false,"database_access":false,
                "application_dispatch":false,"saved_to_job_queue":false})
        ),
        Err(error) => {
            println!(
                "{}",
                json!({"platform":platform,"status":"FAIL","failure_code":error.0,
                    "elapsed_ms":started.elapsed().as_millis(),"requests":requests,
                    "candidate_data_sent":false,"database_access":false,
                    "application_dispatch":false,"saved_to_job_queue":false})
            );
            std::process::exit(1);
        }
    }
}
