//! Deferred reconciliation contract: owner-reported delivery is not provider/application proof.
use automated_apply_agents::execution::{self, telegram_reconciliation::normalize};
use serde_json::{Value, json};
use uuid::Uuid;
#[test]
fn prompt_reconciliation_requires_exact_attempt_and_conditional_message_id_without_resend_parameters()
 {
    let id = Uuid::from_u128(7);
    let sent = json!({"expected_delivery_attempt":id,"outcome":"sent","message_id":33});
    assert_eq!(normalize(sent.clone()).unwrap(), sent);
    assert_eq!(
        normalize(json!({"expected_delivery_attempt":id,"outcome":"not_sent"})).unwrap(),
        json!({"expected_delivery_attempt":id,"outcome":"not_sent","message_id":null})
    );
    for value in [
        Value::Null,
        json!({}),
        json!({"expected_delivery_attempt":"invalid","outcome":"not_sent"}),
        json!({"expected_delivery_attempt":id,"outcome":"sent"}),
        json!({"expected_delivery_attempt":id,"outcome":"sent","message_id":0}),
        json!({"expected_delivery_attempt":id,"outcome":"sent","message_id":-1}),
        json!({"expected_delivery_attempt":id,"outcome":"sent","message_id":"33"}),
        json!({"expected_delivery_attempt":id,"outcome":"sent","message_id":33.0}),
        json!({"expected_delivery_attempt":id,"outcome":"sent","message_id":true}),
        json!({"expected_delivery_attempt":id,"outcome":"sent","message_id":i64::MAX}),
        json!({"expected_delivery_attempt":id,"outcome":"not_sent","message_id":33}),
        json!({"expected_delivery_attempt":id,"outcome":"retry"}),
        json!({"expected_delivery_attempt":id,"outcome":"not_sent","resend":true}),
    ] {
        assert!(normalize(value).is_err());
    }
    let path = format!("/api/v1/execution/questions/{id}/delivery-reconciliation");
    let route = execution::route(&path).unwrap();
    assert_eq!(route.method(), "POST");
    assert_eq!(route.status(), 200);
    assert!(execution::route(&format!("{path}/resend")).is_none());
}
