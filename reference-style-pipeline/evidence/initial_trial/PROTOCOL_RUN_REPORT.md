# Reference-style run report

**Human audit report: do not feed acceptance history back into edit prompts.**

Sample: `Camera0717_A01_B01_camera_rgb_20261101`; purpose: `reference_style`; schema: `reference_style_s4_v6`.
Runtime: current_chat_offline file bridge. Code performs zero model/API calls; external dialogue is caller-attested, not remotely authenticated.

## Inputs / provenance
A is caller-declared camera RGB, not Base output. Scope: camera_rgb_workflow_only; this is not Base-model validation.
Source hashes below identify supplied input bytes, not necessarily upstream camera-original bytes.
Upstream original-to-supplied lineage artifact: `input_lineage.json`, SHA256 `5e9a4667dc87dda365a50937065d8ef095d819f991dee39f045809e365319e34`. Hash-bound external attestation; conversion and upstream provenance are not automatically authenticated.
- A: source `45fde436c1dded521d1bd7e3fccd48b413fbae9ea5eb03ca1573a36e990f0568`, derivative `d9f86bde74ce64c8e242c70b7ca7879d53f98db2051d87c9de30a32a8d318959`, srgb, 8-bit, native [2296, 3056], oriented [2296, 3056].
- B: source `9e7d4adec9ada04f100314598500583ae24ffb72c148f91ad69296e49cf1f374`, derivative `fee936dd6c2f286e9f8bfa395a7e2605177e64d53759001d39acb93854197b30`, srgb, 8-bit, native [2316, 3088], oriented [2316, 3088].

## Budget / attempts
```json
{"basis":"explicit_local_export_limits","config":{"diagnostics":3,"edit_attempts":1,"feedback_rounds":0,"total":4,"version":"b1"},"reservations":[{"kind":"diagnostics","ordinal":1,"refund":"never_automatic","reservation_id":"attempt_801c904796a3406bb361d9be439b959d"},{"kind":"edit_attempts","ordinal":2,"refund":"never_automatic","reservation_id":"attempt_243b3a4bc0764841a8cc6d502c6fc44e"},{"kind":"diagnostics","ordinal":3,"refund":"never_automatic","reservation_id":"attempt_f551ffec32964db38c89b7e1cb08bdb2"},{"kind":"diagnostics","ordinal":4,"refund":"never_automatic","reservation_id":"attempt_9e4db9df61b34bff8c71820e9126a4ad"}],"used":{"diagnostics":3,"edit_attempts":1,"feedback_rounds":0,"total":4}}
```
- `attempt_801c904796a3406bb361d9be439b959d` / ab_diagnosis: **validated**, request `693e527f79321d2f0012cbb77d69782909b62bd3067df3b6e21f8559456b29ef`, prompt `2c31b74dbad098ba5c637023a4e835414d3b7c0e096716896a9786bdaeb08788`; planned attachments 2.
- `attempt_243b3a4bc0764841a8cc6d502c6fc44e` / edit: **validated**, request `76db219f37b57736dd74d9bf0f06dc8c0690c7d706e1ba7e086519a1a7181576`, prompt `c82adf7f5b510c8ccb25b7e70abbe262fa991ab2906d368c42781633693cfa4a`; planned attachments 4.
- `attempt_f551ffec32964db38c89b7e1cb08bdb2` / abc_diagnosis: **validated**, request `9cf7571ee5d2a0de2342883a89f4750bfaa1346e17ae8c1c769e59f4cf1419f9`, prompt `4d43464dede41cef1d0f62abb7e528f8a31963d302776988fd5b012dd1602b28`; planned attachments 3.
- `attempt_9e4db9df61b34bff8c71820e9126a4ad` / abc_diagnosis: **validated**, request `b145115e7f862bd9af2be758189d9e9372b8f022a2287d1ae356f58f798cd4c9`, prompt `a7b44d4fd43be219ade8449c8eaaf593c54892d9f275d3adcd8c1f7247cd9a7c`; planned attachments 6.

## Actual stage records
- evidence: 20 record(s)
  - `e1` / `tool_evidence_bacb6d78b6674828b950faf21f758d69` / `cc48a5ea69e6c42ef376ee6853e5c99f741e650b78147cddaf4546fcb7dc34a1`: available
  - `e10` / `tool_evidence_cc8391c577554dd5b0bf3e17211ae5f4` / `938c7dd0ec39ee743023cf1d88d6cfe66694d75ee1506278b5054d79e504a500`: available
  - `e11` / `tool_evidence_ce6d34be3a6045f7837442c5c75d27ac` / `47d162cda9043fd4b457f28cb89eb1cfd136e99bf0a09e3c7aa5d477eaf416cd`: available
  - `e12` / `tool_evidence_e6b9b38e002c4fd4b1cf022ba6513abc` / `c02b900f00ee0765c95bff7eade5e813e4e2f677eda204f29fdbb3dfb0c1687d`: uncertain
  - `e13` / `tool_evidence_43d6a27efaad49d48679211ac4aef857` / `986bd9ac3a6233f2cd5fee65fbf2d91a21c08819da1c616c421f6189c0ff56ea`: uncertain
  - `e14` / `tool_evidence_856f2ceb68ea4ca6a7e330a096a07112` / `7126fba7c79b660f163a803ec844c0e695cc4ad3731f718a9d8b7804caf16a30`: uncertain
  - `e15` / `tool_evidence_d653bf3a92c64d34934fd6ce4e6dd14e` / `778632e3e35b46da21a1804e4b1b7f4148b8a9735de03430bb3eeed155e14767`: unavailable
  - `e16` / `tool_evidence_67ef96063b2b441ea1156315102ef700` / `7cc9a2c0ccb8b910fdfab6e363d3d57206f1364c41bb89e02079a6799bde14ac`: unavailable
  - `e17` / `tool_evidence_0780c126108f4b1191411e59a9796d2c` / `abf7e66b97739b43f44bea9e6019ab05cf93f719affc89d484fc6ea3861e381c`: unavailable
  - `e18` / `tool_evidence_4f3e424180e84d78aeb127aeeccccd4d` / `6d556010202d5329526d6ad8f8ccd6991072338c466a871b43cad4b1286edc41`: unavailable
  - `e19` / `tool_evidence_1118f99a2def42d09300f5044e6ff2c5` / `709914a47284afcecb63f29204e31582c1f88c35d5b82e41a7df1f05fd4f1b68`: unavailable
  - `e2` / `tool_evidence_82889d56c7ab4331aadfe294df50572b` / `05c063d38d07b9d36bc5458080594d16e3f129d2d3cc81876f5d773135784458`: available
  - `e20` / `tool_evidence_e7caec400b8e47d589f8cef2cad8e656` / `5150f547366e0ddd4323106dc664982a0f19fb0bce12ae8b590adc2d52f7da35`: unavailable
  - `e3` / `tool_evidence_4b77040039ee4fa69f9a235d28556864` / `dda8ca31d3e7623a887ba38d1018d2a325fbbbbfc69fd527ab8b3ac9e5545359`: available
  - `e4` / `tool_evidence_f0118321f8c345e4aa69897e268e5cf7` / `793f49307fb5c5d538b3fddd45de5f7b3faa2b68463357501f0875e08a62eecf`: available
  - `e5` / `tool_evidence_a4d05ff905ff4b7f961091b9fcb7785e` / `baddc3d2ca9e09664ce99709395c7ced54d1f2778c63896c589e3c360cafbdb4`: uncertain
  - `e6` / `tool_evidence_cfe8b3f1c83547c094e798040af30a50` / `b441af4fe11f2a552870277509f50009a44b31f1e74788eebc5b91052d5c6d58`: uncertain
  - `e7` / `tool_evidence_7d5770d97ecf4402bd8fafc54e0919f8` / `1f09874466d669cc162c9d415fe82eaeeabf9f3410760be1b64f56d3ffb5f065`: uncertain
  - `e8` / `tool_evidence_f291301b49f54da8910ad3c9cba571d6` / `163daa983cf7c6adef820eb52ebdb8c2fe22bab09d5cf685eeab159868e5a5ce`: available
  - `e9` / `tool_evidence_149b9d4d79dc47fbad46485d4d6977b6` / `2cef8baefa37c75f26bf041e0d456f36c80ea942533713142be72956466eafec`: available
- snapshots: 1 record(s)
  - `s1` / `region_snapshot_87977fa47bf149c98dd66c3f98000055` / `e5730b2097dd12d42819c84de767e44ab4aab80f053c41fd59dcb06118daf25f`: recorded
- reports: 1 record(s)
  - `ab_report_e665c65e38a340c59b16445c79a01c55` / `ab_report_e665c65e38a340c59b16445c79a01c55` / `43ef76d1a045be4de189e31fb446cbf50fb206d9bc57f593fb3192955b45f020`: numeric_observed_visual_diagnosis_pending
- targets: 1 record(s)
  - `v1` / `style_targets_f3c2373757af482e96138eab798c738d` / `4c7706eec604d9477133ac903f1db7def33f0d0b48e15e98ae8192abef247926`: caller_attested_diagnosis_imported_not_independently_verified
- compiled: 1 record(s)
  - `compiled_request_791ca8c0a50946ec8e26f78b4595c5d5` / `compiled_request_791ca8c0a50946ec8e26f78b4595c5d5` / `3ae6068ba3d6cc9a539a715e1b77c345282af17bb1219b688a6c5c80c66c7313`: recorded
- submissions: 3 record(s)
  - `attempt_243b3a4bc0764841a8cc6d502c6fc44e` / `dialog_submission_e7c0acc1980e4767b7021f5c350969cc` / `ef7a44a235cd7bc56d3aa5defaba8a475c7b86dc82cafe07190532a25ac7f980`: matches_plan
```json
{"package_status":"matches_plan","provenance_verification":"caller_attested_not_remote_authenticated","remote_input_visibility":"unknown","submitted_attachments":[{"attachment_id":"a1","ordinal":1,"purpose":"content_image","role":"A","sha256":"d9f86bde74ce64c8e242c70b7ca7879d53f98db2051d87c9de30a32a8d318959"},{"attachment_id":"a2","ordinal":2,"purpose":"style_reference","role":"B","sha256":"fee936dd6c2f286e9f8bfa395a7e2605177e64d53759001d39acb93854197b30"},{"attachment_id":"a3","ordinal":3,"purpose":"localization_only","role":"A","sha256":"a36dc6e4d9db5f8936a9deb5cc4b01efefab2362fc69caff9a87ca95b9e00be6"},{"attachment_id":"a4","ordinal":4,"purpose":"localization_only","role":"B","sha256":"9060bd7a2a0c8d95ef75ab606b55c10f279a424e60f011eea74b012ac9c4f9c3"}],"submitted_prompt_hash":"c82adf7f5b510c8ccb25b7e70abbe262fa991ab2906d368c42781633693cfa4a"}
```
  - `attempt_9e4db9df61b34bff8c71820e9126a4ad` / `dialog_submission_c0533f846dae41bfaaec407b2ddbff39` / `0575e364eaa05a5155e49aedb2b0fdb2439e69d6a24ccd618a34afcda9fc413d`: matches_plan
```json
{"package_status":"matches_plan","provenance_verification":"caller_attested_not_remote_authenticated","remote_input_visibility":"unknown","submitted_attachments":[{"attachment_id":"a1","ordinal":1,"purpose":"content_image","role":"A","sha256":"d9f86bde74ce64c8e242c70b7ca7879d53f98db2051d87c9de30a32a8d318959"},{"attachment_id":"a2","ordinal":2,"purpose":"style_reference","role":"B","sha256":"fee936dd6c2f286e9f8bfa395a7e2605177e64d53759001d39acb93854197b30"},{"attachment_id":"a3","ordinal":3,"purpose":"candidate_observation","role":"C","sha256":"536d4f004fd4e2586153f5b76933b57f0689c289cefd2b56e78cfac1c0f95aaf"},{"attachment_id":"a4","ordinal":4,"purpose":"localization_only","role":"A","sha256":"a36dc6e4d9db5f8936a9deb5cc4b01efefab2362fc69caff9a87ca95b9e00be6"},{"attachment_id":"a5","ordinal":5,"purpose":"localization_only","role":"B","sha256":"9060bd7a2a0c8d95ef75ab606b55c10f279a424e60f011eea74b012ac9c4f9c3"},{"attachment_id":"a6","ordinal":6,"purpose":"localization_only","role":"C","sha256":"ec25edcdfa13bdbdf31dc3a98c55e0f64882bfb59667c5a2cfed3b6cd2a2fe10"}],"submitted_prompt_hash":"a7b44d4fd43be219ade8449c8eaaf593c54892d9f275d3adcd8c1f7247cd9a7c"}
```
  - `attempt_f551ffec32964db38c89b7e1cb08bdb2` / `dialog_submission_971c50526dc4430084318332a9591402` / `5b089d450e36d911b0dfeda66bb7247979faa35dfb9009b0e3d743e5d990d319`: matches_plan
```json
{"package_status":"matches_plan","provenance_verification":"caller_attested_not_remote_authenticated","remote_input_visibility":"unknown","submitted_attachments":[{"attachment_id":"a1","ordinal":1,"purpose":"content_image","role":"A","sha256":"d9f86bde74ce64c8e242c70b7ca7879d53f98db2051d87c9de30a32a8d318959"},{"attachment_id":"a2","ordinal":2,"purpose":"style_reference","role":"B","sha256":"fee936dd6c2f286e9f8bfa395a7e2605177e64d53759001d39acb93854197b30"},{"attachment_id":"a3","ordinal":3,"purpose":"candidate_observation","role":"C","sha256":"536d4f004fd4e2586153f5b76933b57f0689c289cefd2b56e78cfac1c0f95aaf"}],"submitted_prompt_hash":"4d43464dede41cef1d0f62abb7e528f8a31963d302776988fd5b012dd1602b28"}
```
- candidate_derivatives: 1 record(s)
  - `response_818b2ab9cd6344d9a613a3bd1e9a0e37_d1` / `candidate_derivative_916dcd52b38a4854bb8d45cd454d7205` / `ddffe6f9a3babcebfd6f44498a44a56bdb1265d449947c66c7d87beeeceed99c`: assumed_display_only
```json
{"geometry":{"crop":null,"exif_orientation_applied":1,"native_size":[1087,1446],"numeric_support_status":"uncertain","orientation":1,"oriented_size":[1087,1446],"resize":null,"size_matches_A":false,"spatial_correspondence":"unverified"},"raw_candidate_hash":"15f89e550fb28a661bd3b27ef53c51e62f416d5fbde07ff0512f7a01798431c6","raw_output_path":"attempts/attempt_243b3a4bc0764841a8cc6d502c6fc44e/raw_response.bin","selected_derivative_audit":{"conversion_chain":["assumed_srgb_visual_only","sRGB_piecewise_transfer_decode","D65_matrix_to_linear_srgb","sRGB_piecewise_transfer_encode","explicit_endpoint_clip","round_to_RGB8"],"derivative_file_hash":"536d4f004fd4e2586153f5b76933b57f0689c289cefd2b56e78cfac1c0f95aaf","derivative_path":"s3/candidate_assets/response_818b2ab9cd6344d9a613a3bd1e9a0e37_d1/input.png","derivative_pixel_hash":"a699120c7f6de5485364b9e0a0270e759accbe165f77737e11a25adcfde10210","native_size":[1087,1446],"numeric_status":"blocked_unknown_encoding","oriented_size":[1087,1446],"source_encoding":"unknown"},"spatial_correspondence":"unverified","status":"assumed_display_only","visual_style_status":"not_evaluated"}
```
- evaluation_versions: 1 record(s)
  - `q1` / `evaluation_version_3916c743cc8c4c5aa26d17a4fd809205` / `d088490284727252fa523e60b5213500420efec91c05816f034caa9c2b7fbe83`: recorded
- candidate_supports: 1 record(s)
  - `k1` / `candidate_support_eecb999404304894851d8ff8af4ae2dc` / `0c5a34821a91795a9379b1311bd2f8df4112980e0c30ce1bc263dd2b5b870c27`: recorded
- evaluations: 1 record(s)
  - `j1` / `candidate_evaluation_93ba3e346fee48d58eeb18c548d0a912` / `4eec7ffc31e6f22fb2e053049e2656a16586532e09c6a4028ce122e9d559aa64`: recorded
- facts: 1 record(s)
  - `f1` / `ABC_facts_e9cafa1adee048068dfd71904bbb16e1` / `06d4723a5a06dba649171066669b52fbda3e0350e20a9fab609fa2d9c332e323`: recorded
```json
{"content_spatial":{"geometry":{"confidence":"medium","severity":"unknown"},"identity":{"confidence":"medium","severity":"unknown"},"layout":{"confidence":"medium","severity":"none_observed"},"naturalness":{"confidence":"medium","severity":"minor_local_incidental"},"ocr":{"confidence":"unknown","severity":"unknown"},"texture":{"confidence":"medium","severity":"unknown"}},"overall_style":{"brightness":{"confidence":"medium","status":"partial"},"color":{"confidence":"medium","status":"partial"},"tone":{"confidence":"medium","status":"partial"}},"review_order":"image_first_then_evidence","reviewer":{"independence":"same_model","reviewer_id":"parent_current_chat"},"spillover":[],"targets":[{"confidence":"medium","residual_code":"tone_residual","status":"partial","target_id":"t1"},{"confidence":"medium","residual_code":"too_warm","status":"partial","target_id":"t2"},{"confidence":"medium","residual_code":"too_bright","status":"partial","target_id":"t3"},{"confidence":"medium","residual_code":"too_bright","status":"partial","target_id":"t4"},{"confidence":"medium","residual_code":"too_warm","status":"partial","target_id":"t5"},{"confidence":"medium","residual_code":"too_dark","status":"partial","target_id":"t6"},{"confidence":"medium","residual_code":"tone_residual","status":"partial","target_id":"t7"},{"confidence":"medium","residual_code":"too_saturated","status":"partial","target_id":"t8"},{"confidence":"medium","residual_code":"too_bright","status":"partial","target_id":"t9"},{"confidence":"medium","residual_code":"tone_residual","status":"partial","target_id":"t10"},{"confidence":"medium","residual_code":"none_observed","status":"achieved","target_id":"t11"},{"confidence":"medium","residual_code":"relationship_residual","status":"partial","target_id":"t12"},{"confidence":"medium","residual_code":"uncertain","status":"partial","target_id":"t13"},{"confidence":"medium","residual_code":"none_observed","status":"achieved","target_id":"t14"},{"confidence":"high","residual_code":"none_observed","status":"achieved","target_id":"t15"},{"confidence":"medium","residual_code":"none_observed","status":"achieved","target_id":"t16"},{"confidence":"medium","residual_code":"none_observed","status":"achieved","target_id":"t17"},{"confidence":"high","residual_code":"none_observed","status":"achieved","target_id":"t18"}]}
```
- feedback: **NOT RUN / unavailable**
- selections: **NOT RUN / unavailable**
- failures: **NOT RUN / unavailable**

## Candidate ABC numeric / visual findings
```json
{"candidate_measurement_basis":"selected_C_artifact_v1","native_diagnostics_use":"separate_raw_only_not_final_artifact_acceptance","selected_artifact":{"analysis_file_hash":null,"analysis_path":null,"analysis_source_file_hash":null,"bit_depth":8,"encoding":"srgb","file_hash":"536d4f004fd4e2586153f5b76933b57f0689c289cefd2b56e78cfac1c0f95aaf","numeric_status":"blocked_unknown_encoding","path":"s3/candidate_assets/response_818b2ab9cd6344d9a613a3bd1e9a0e37_d1/input.png","pixel_hash":"a699120c7f6de5485364b9e0a0270e759accbe165f77737e11a25adcfde10210","precision":"exact_selected_RGB8_values_in_float64_not_restored_native_precision"}}
```
### j1 / q1
Raw C `15f89e550fb28a661bd3b27ef53c51e62f416d5fbde07ff0512f7a01798431c6`; selected derivative record `ddffe6f9a3babcebfd6f44498a44a56bdb1265d449947c66c7d87beeeceed99c`.
Generation target `4c7706eec604d9477133ac903f1db7def33f0d0b48e15e98ae8192abef247926`; evaluation target `4c7706eec604d9477133ac903f1db7def33f0d0b48e15e98ae8192abef247926`.
| Measure | A | B | C | C_minus_B | C_minus_A | baseline_absolute_residual | candidate_absolute_residual | Absolute improvement | Eligibility |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| g0/linear_Y/q50 | 0.14618054444257522 | 0.34257554161808346 | None | None | None | 0.19639499717550823 | None | None | visual_direction_only |
| g0/linear_Y/span95_05 | 0.857921684338952 | 0.9306881197272208 | None | None | None | 0.07276643538826877 | None | None | visual_direction_only |
| g0/L_star/q50 | 45.10796509546651 | 65.16664113767288 | None | None | None | 20.058676042206372 | None | None | visual_direction_only |
| g0/L_star/span95_05 | 75.24307924572433 | 75.8413081827259 | None | None | None | 0.598228937001565 | None | None | visual_direction_only |
| g0/a_star/q50 | 1.9725949747566585 | 9.245643467211572 | None | None | None | 7.2730484924549135 | None | None | visual_direction_only |
| g0/a_star/span95_05 | 35.748422375581455 | 57.23350597653742 | None | None | None | 21.485083600955967 | None | None | visual_direction_only |
| g0/b_star/q50 | 6.38764570126682e-06 | 11.094302650306819 | None | None | None | 11.094296262661118 | None | None | visual_direction_only |
| g0/b_star/span95_05 | 46.22964816183007 | 71.7324696889199 | None | None | None | 25.502821527089836 | None | None | visual_direction_only |
| g0/chroma/q50 | 16.369141450490773 | 22.305915495095082 | None | None | None | 5.936774044604309 | None | None | visual_direction_only |
| g0/chroma/span95_05 | 40.17475993124403 | 74.34591812195471 | None | None | None | 34.17115819071068 | None | None | visual_direction_only |
Verification: **NOT RUN**; no acceptance or pixel-label claim.

## Unverified / NOT RUN items
- Same-goal deterministic comparison and batch stability: **NOT RUN / UNVERIFIED**.
- Training utility, pixel-label certification and downstream X pairing: **NOT RUN**.
- Qwen server execution: **NOT INTEGRATED / NOT RUN**. Existing native bridge needs an explicit provider adapter and new provenance/receipt mapping; never label Qwen output as a ChatGPT receipt.
- Real calibration/approval is only the supplied versioned artifact attestation; synthetic_fixture data never establishes real style performance.
- Unknown/failed requests retain reservations. No fallback A is a successful C.
