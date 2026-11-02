# Project Memory

- Expression, gaze, smile, mouth opening and mood follow the style image. The scheme face close-up anchors stable facial structure only, not a fixed expression. Extract expressions during style analysis and allow their normal facial changes during review.

- Refresh omits finished jobs without visible results and removes empty/failed slots from partial finished jobs. Preserve queued/running slots and uncertain submissions. This is response filtering only: stored jobs, idempotency keys and credit reconciliation remain intact.

- New works use `scheme-four-v1`: exactly front, side, back and face close-up from the selected scheme, then one style image. Never substitute uploads or reread upload accessories for these jobs. Freeze the references and scheme accessories at job creation. Review against the scheme face close-up. Keep legacy jobs on their original method for safe retries.

- Generated-work deletion marks completed slots as deleted rather than removing job or credit records. Retain their internal asset identifiers so partial-task retries cannot regenerate deleted completed slots. Public job responses omit deleted slots. Remove unreferenced asset records and files; preserve shared assets referenced by profiles or other submitted tasks.
