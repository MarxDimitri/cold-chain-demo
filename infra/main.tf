terraform {
  required_version = ">= 1.5"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.5" }
    local  = { source = "hashicorp/local", version = "~> 2.5" }
  }
}

provider "aws" {
  region  = var.region
  profile = var.profile

  default_tags {
    tags = {
      project      = var.project_tag
      team         = var.team
      org          = "sa"
      division     = "field"
      "keep-until" = var.keep_until
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  chain      = yamldecode(file("${path.module}/../config/chain.yaml"))
  store_ids  = toset([for s in local.chain.stores : s.id])
  bucket     = "${var.bucket_prefix}-${random_id.suffix.hex}"
  bucket_arn = aws_s3_bucket.this.arn
  account_id = data.aws_caller_identity.current.account_id
}

resource "random_id" "suffix" {
  byte_length = 3
}

# ---------------------------------------------------------------- bucket (central IT)

resource "aws_s3_bucket" "this" {
  bucket              = local.bucket
  object_lock_enabled = true
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Governance mode with a short retention so teardown stays possible (needs s3:BypassGovernanceRetention).
resource "aws_s3_bucket_object_lock_configuration" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.object_lock_days
    }
  }
  depends_on = [aws_s3_bucket_versioning.this]
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket                  = aws_s3_bucket.this.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "tls_only" {
  bucket = aws_s3_bucket.this.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [local.bucket_arn, "${local.bucket_arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.this]
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    id     = "expire-noncurrent-and-multipart"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.object_lock_days + 1
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 2
    }
  }
  depends_on = [aws_s3_bucket_versioning.this]
}

# ---------------------------------------------------------------- detect/ notifications -> SQS

resource "aws_sqs_queue" "dlq" {
  name                      = "${local.bucket}-detect-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "detect" {
  name                       = "${local.bucket}-detect"
  visibility_timeout_seconds = 300 # Elastic Agent AWS S3 input default
  receive_wait_time_seconds  = 20
  message_retention_seconds  = 345600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue_policy" "from_s3" {
  queue_url = aws_sqs_queue.detect.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.detect.arn
      Condition = {
        ArnEquals    = { "aws:SourceArn" = local.bucket_arn }
        StringEquals = { "aws:SourceAccount" = local.account_id }
      }
    }]
  })
}

resource "aws_s3_bucket_notification" "detect" {
  bucket = aws_s3_bucket.this.id
  queue {
    queue_arn     = aws_sqs_queue.detect.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "detect/"
  }
  depends_on = [aws_sqs_queue_policy.from_s3]
}

# ---------------------------------------------------------------- identities

# One write-only user per store: PutObject on its own prefix only (no read, list or delete).
resource "aws_iam_user" "store" {
  for_each = local.store_ids
  name     = "${var.bucket_prefix}-store-${each.key}"
}

resource "aws_iam_user_policy" "store" {
  for_each = local.store_ids
  name     = "write-own-prefix"
  user     = aws_iam_user.store[each.key].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:PutObject"]
      Resource = [
        "${local.bucket_arn}/detect/dataset=*/store=${each.key}/*",
        "${local.bucket_arn}/raw/dataset=*/store=${each.key}/*",
      ]
    }]
  })
}

resource "aws_iam_access_key" "store" {
  for_each = local.store_ids
  user     = aws_iam_user.store[each.key].name
}

# Central collector: reads detect/* and consumes the notification queue.
resource "aws_iam_user" "collector" {
  name = "${var.bucket_prefix}-collector"
}

resource "aws_iam_user_policy" "collector" {
  name = "read-detect-and-queue"
  user = aws_iam_user.collector.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${local.bucket_arn}/detect/*" },
      {
        Effect    = "Allow"
        Action    = ["s3:ListBucket"]
        Resource  = local.bucket_arn
        Condition = { StringLike = { "s3:prefix" = ["detect/*"] } }
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes", "sqs:GetQueueUrl"]
        Resource = aws_sqs_queue.detect.arn
      },
    ]
  })
}

resource "aws_iam_access_key" "collector" {
  user = aws_iam_user.collector.name
}

# Federation data source: reads raw/* only. A federated-identity role replaces this once
# Elastic's trust details for the deployment are confirmed (see docs/decisions.md).
resource "aws_iam_user" "federation" {
  name = "${var.bucket_prefix}-federation"
}

resource "aws_iam_user_policy" "federation" {
  name = "read-raw"
  user = aws_iam_user.federation.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${local.bucket_arn}/raw/*" },
      {
        Effect    = "Allow"
        Action    = ["s3:ListBucket"]
        Resource  = local.bucket_arn
        Condition = { StringLike = { "s3:prefix" = ["raw/*", "raw"] } }
      },
      { Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = local.bucket_arn },
    ]
  })
}

resource "aws_iam_access_key" "federation" {
  user = aws_iam_user.federation.name
}

# ---------------------------------------------------------------- credentials for the generator

resource "local_sensitive_file" "store_keys" {
  filename        = "${path.module}/../store-keys.json"
  file_permission = "0600"
  content = jsonencode({
    for id, k in aws_iam_access_key.store : id => { access_key_id = k.id, secret_access_key = k.secret }
  })
}
