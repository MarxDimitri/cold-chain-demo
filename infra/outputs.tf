output "bucket" {
  value = aws_s3_bucket.this.id
}

output "region" {
  value = var.region
}

output "detect_queue_url" {
  value = aws_sqs_queue.detect.id
}

output "detect_queue_arn" {
  value = aws_sqs_queue.detect.arn
}

output "detect_dlq_url" {
  value = aws_sqs_queue.dlq.id
}

output "collector_credentials" {
  value     = { access_key_id = aws_iam_access_key.collector.id, secret_access_key = aws_iam_access_key.collector.secret }
  sensitive = true
}

output "federation_credentials" {
  value     = { access_key_id = aws_iam_access_key.federation.id, secret_access_key = aws_iam_access_key.federation.secret }
  sensitive = true
}
