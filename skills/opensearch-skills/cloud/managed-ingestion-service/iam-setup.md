## IAM Role Setup (if needed)

If the user does not have an existing OSIS role:

**Create role with trust policy:**
```bash
aws iam create-role \
  --role-name <role-name> \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "osis-pipelines.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'
```

**Attach S3 read permission:**
```bash
aws iam put-role-policy \
  --role-name <role-name> \
  --policy-name S3ReadAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetBucketLocation", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::<bucket>", "arn:aws:s3:::<bucket>/*"]
    }]
  }'
```

**Attach OpenSearch write permission (for AOSS):**
```bash
aws iam put-role-policy \
  --role-name <role-name> \
  --policy-name AOSSWriteAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "aoss:BatchGetCollection",
        "aoss:APIAccessAll",
        "aoss:CreateIndex",
        "aoss:GetSecurityPolicy",
        "aoss:CreateSecurityPolicy",
        "aoss:UpdateSecurityPolicy"
      ],
      "Resource": "*"
    }]
  }'
```

**Attach OpenSearch write permission (for AOS):**
```bash
aws iam put-role-policy \
  --role-name <role-name> \
  --policy-name AOSWriteAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "es:DescribeDomain",
        "es:ESHttpHead",
        "es:ESHttpGet",
        "es:ESHttpPut",
        "es:ESHttpPost"
      ],
      "Resource": "arn:aws:es:<region>:<account-id>:domain/<domain-name>/*"
    }]
  }'
```

> **Why extra permissions for semantic_enrichment?** The ASE sink **creates the index itself**
> and manages ML resources. For AOSS: needs `aoss:CreateIndex`, `aoss:GetSecurityPolicy`,
> `aoss:CreateSecurityPolicy`, `aoss:UpdateSecurityPolicy`. For AOS: needs `es:CreateIndex`
> (v2.19+). A plain OSIS sink only needs basic write permissions.

**Update AOSS data access policy** (AOSS only) — add the OSIS role as a principal:

**Step 1: Get the current policy (version + body):**
```bash
aws opensearchserverless get-access-policy --type data \
  --name <collection-name>-access-policy --region <region>
```

Note `policyVersion` from the response — required for the update call.

**Step 2: Merge the OSIS role into the existing policy.**

Inspect the current `policy` JSON from Step 1. Add `<osis-role-arn>` to the existing
`Principal` array. If `model` and `agent` ResourceType rules are missing, add them
(required for `semantic_enrichment`). **Do NOT replace the entire policy** — preserve
all existing rules and principals.

The merged policy must include at minimum:
```json
"Rules": [
  {"Resource": ["collection/<collection-name>"], "Permission": ["aoss:*"], "ResourceType": "collection"},
  {"Resource": ["index/<collection-name>/*"], "Permission": ["aoss:*"], "ResourceType": "index"},
  {"Resource": ["model/<collection-name>/*"], "Permission": ["aoss:*"], "ResourceType": "model"},
  {"Resource": ["agent/<collection-name>/*"], "Permission": ["aoss:*"], "ResourceType": "agent"}
]
```

**Step 3: Update with the merged policy:**
```bash
aws opensearchserverless update-access-policy --type data \
  --name <collection-name>-access-policy \
  --policy-version "<current-version>" \
  --policy '<merged-policy-json>' --region <region>
```

**Important:** Preserve existing rules and principals. Only append the OSIS role ARN to
the existing `Principal` array. Wait ~30 seconds for propagation.

> **`model` / `agent` ResourceTypes are required for `semantic_enrichment` on AOSS.** ASE
> deploys a sparse model server-side, so the data access policy must grant `model` (and
> `agent`, used for agentic search) in addition to `collection` + `index`.

> **After changing the OSIS role's IAM permissions, stop and start the pipeline.** OSIS caches
> the assumed-role credentials:
> ```bash
> aws osis stop-pipeline  --pipeline-name <pipeline-name> --region <region>   # wait for STOPPED
> aws osis start-pipeline --pipeline-name <pipeline-name> --region <region>
> ```

---

