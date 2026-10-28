import test from "node:test";
import assert from "node:assert/strict";
import { naukriFormUrl } from "../naukri.js";

test("Naukri local assistance accepts a selected clean posting only", () => {
  assert.equal(naukriFormUrl("https://www.naukri.com/job-listings-fictional-backend-281026123456"), true);
  for (const url of [
    "https://www.naukri.com/login",
    "https://www.naukri.com/mnjuser/profile",
    "https://www.naukri.com/job-listings-fictional-281026123456?token=x",
    "https://www.naukri.com/job-listings-fictional-281026123456#login",
    "https://naukri.com.attacker.example/job-listings-fictional-281026123456",
    "https://u:p@www.naukri.com/job-listings-fictional-281026123456",
    "http://www.naukri.com/job-listings-fictional-281026123456",
    "https://www.naukri.com:8443/job-listings-fictional-281026123456",
  ]) assert.equal(naukriFormUrl(url), false, url);
});
