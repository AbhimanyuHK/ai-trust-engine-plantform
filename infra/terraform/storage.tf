resource "aws_s3_bucket" "contracts" {
  bucket        = var.contract_bucket_name
  force_destroy = var.environment != "prod"
  tags          = local.tags
}
resource "aws_s3_bucket_versioning" "contracts" {
  bucket = aws_s3_bucket.contracts.id
  versioning_configuration {
    status = "Enabled"
  }
}
resource "aws_kms_key" "documents" {
  description             = format("%s S3 document encryption", local.prefix)
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = local.tags
}
resource "aws_kms_alias" "documents" {
  name          = format("alias/%s-documents", local.prefix)
  target_key_id = aws_kms_key.documents.key_id
}
resource "aws_s3_bucket_server_side_encryption_configuration" "contracts" {
  bucket = aws_s3_bucket.contracts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.documents.arn
    }
    bucket_key_enabled = true
  }
}
resource "aws_s3_bucket_public_access_block" "contracts" {
  bucket                  = aws_s3_bucket.contracts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
