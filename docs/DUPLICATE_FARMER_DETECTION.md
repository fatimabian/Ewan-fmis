# Farmer duplicate detection

## Current production-safe baseline

FMIS uses a bounded, server-side fuzzy similarity check immediately before a new
farmer registration is saved. It preserves the existing exact identification-number
validation. The fuzzy check never automatically rejects, merges, deletes, or changes
a farmer record.

Candidate retrieval uses first-name and last-name prefixes, barangay, birthdate, and
identification agreement. The database returns at most 120 candidates; Python scores
only those rows and returns at most five review matches. Normal Farmer Master List
searches and page loads do not run duplicate scoring.

The score combines normalized edit similarity for first, middle, last, and full names
with birthdate, barangay, suffix, and identification agreement. Staff see a clearly
labeled rule-based percentage and the reasons for the flag. Sensitive identification
numbers, contact details, and documents are not returned by the review endpoint.

Staff can open an existing record or confirm a separate farmer with a required reason.
The signed review token is bound to the entered identity and candidate IDs, expires
after 20 minutes, and is revalidated on the final POST. The decision and candidate
record IDs are written to the activity log.

## Machine-learning status

No ML model is active. FMIS must not describe this baseline as machine learning.
There is currently no verified labeled pair dataset from the Office for Agricultural
Services, so training a Random Forest would produce unsupported accuracy claims.

## Dataset required before ML can be enabled

OAS must review candidate pairs and label each as `duplicate` or `separate`. Each row
should use internal record IDs rather than raw identification numbers and must be kept
outside public/static/media directories. The dataset should include spelling errors,
missing middle names, suffix variations, shared family names, changed barangays,
missing IDs, and verified distinct people with similar names.

Train/test splitting must group by underlying person so the same identity cannot occur
in both sets. Candidate-retrieval recall must be evaluated separately from classifier
precision, recall, F1, and confusion matrix. A fuzzy-only baseline must be evaluated on
the same held-out pairs. Only a versioned model that improves the agreed safety metric
should be enabled, with its dataset version, feature schema, threshold, and evaluation
report stored beside the private artifact.

## Known limitations

- A fuzzy score is a review aid, not proof of identity.
- Records outside the bounded blocking query cannot be scored.
- Missing or incorrect birthdates and barangays reduce confidence.
- Filipino name-order and nickname variation may require future verified alias rules.
- Exact-ID validation remains the authoritative hard duplicate control.

## Staff testing checklist

- Exact identification number remains blocked.
- Exact names, spelling mistakes, spacing/case changes, missing middle names, and suffix
  variants produce appropriate review candidates.
- Different people with similar names can be confirmed separately with a reason.
- Review Existing Record opens the correct farmer.
- A changed identity invalidates an earlier confirmation token.
- No candidate request loads the full farmer table or exposes identification numbers.
- Registration still succeeds when no candidates exist or the check service has no ML
  artifact.
