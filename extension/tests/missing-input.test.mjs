import assert from "node:assert/strict";
import test from "node:test";
import { formPlanText, missingInputLinks } from "../form-messages.js";

test("unknown answers identify durable questions without inventing answers", () => {
  const id = "a".repeat(32);
  const plan = {
    inspection: {
      fields: [{ field_id: "f0", label: "Hardest bug you solved" }],
    },
    actions: [
      {
        field_id: "f0",
        kind: "textarea",
        needs_input: true,
        missing_input_id: id,
      },
    ],
  };
  assert.match(formPlanText(plan), /NEEDS_INPUT: Saved question/);
  assert.deepEqual(missingInputLinks(plan), [
    {
      id,
      label: "Hardest bug you solved",
      url: `http://127.0.0.1:3000/profile?missing_input=${id}`,
    },
  ]);
  assert.doesNotMatch(formPlanText(plan), /undefined/);
});

test("question links reject page-controlled IDs and duplicate links", () => {
  const id = "b".repeat(32);
  assert.equal(
    missingInputLinks({
      actions: [
        { needs_input: true, missing_input_id: "javascript:alert(1)" },
        { needs_input: true, missing_input_id: id },
        { needs_input: true, missing_input_id: id },
        { needs_input: false, missing_input_id: "c".repeat(32) },
      ],
    }).length,
    1,
  );
});
