# VocabLab AI Launch QA Checklist

Use this checklist before each production deploy and before any marketing push.

## 1. Student Account Flow

- [ ] New student can sign up with email, password, and confirm password.
- [ ] Student can log out and log back in.
- [ ] Wrong password shows a clear error.
- [ ] Account settings save display name and non-teacher role.
- [ ] Student cannot switch to teacher without a valid teacher invite code.

## 2. First Student Journey

- [ ] First dashboard shows one clear main mission: start the DSE level test.
- [ ] Starting a DSE level test creates 100 questions.
- [ ] The test uses random words across DSE bands, not only A words.
- [ ] Traditional Chinese UI shows layer instructions in Traditional Chinese.
- [ ] Simplified Chinese UI shows layer instructions in Simplified Chinese.
- [ ] Level test can be resumed after closing the browser or refreshing.
- [ ] Level test result is saved after completion.

## 3. Post-Level-Test Flow

- [ ] Result page shows the recommended DSE band.
- [ ] Primary button starts the recommended learning practice.
- [ ] Secondary options are limited to statistics and retake test.
- [ ] Full report shows layer analysis and band performance.
- [ ] Statistics page shows the latest level test result.

## 4. Learning Session Flow

- [ ] Learning page recommends the band from the latest level test.
- [ ] Student can manually choose any of the 5 DSE bands.
- [ ] Each learning session contains 10 words from the selected band.
- [ ] Learning session uses the 5 layer question structure.
- [ ] Learning session result is saved after completion.
- [ ] Result page shows words completed and words needing review.
- [ ] If mistakes exist, primary action is to review mistakes.
- [ ] If no mistakes exist, primary action is to start the next 10 words.

## 5. Word Mastery And Deep Learning

- [ ] Dictionary word cards show mastery status clearly.
- [ ] Word detail page shows total mastery percentage.
- [ ] Five-layer test progress is separated from Deep Learning progress.
- [ ] Pronunciation button appears on relevant word/question pages.
- [ ] If AI pronunciation check fails, the user sees a helpful fallback message.
- [ ] Sentence usage check returns grammar, usage, correction, and suggested upgrade.
- [ ] API quota errors do not crash the page.

## 6. Teacher Flow

- [ ] Teacher signup requires a valid teacher invite code.
- [ ] Existing non-teacher user cannot become teacher without invite code.
- [ ] Teacher can create a class.
- [ ] Class invite code appears clearly.
- [ ] Student can join class from account settings using the invite code.
- [ ] Teacher can create an assignment for a class.
- [ ] Student can see and start assigned practice.
- [ ] Teacher dashboard shows student activity, accuracy, weak area, risk, and next action.
- [ ] Teacher can export a class CSV report.

## 7. Admin Flow

- [ ] Admin dashboard is hidden from normal users.
- [ ] Admin can see total users, teachers, students, classes, and daily usage.
- [ ] Admin daily usage counts level tests, learning sessions, and Deep Learning attempts.
- [ ] Admin user overview shows role, joined date, last active, and activity counts.

## 8. Mobile Web / Mobile App Checks

- [ ] Web dashboard is usable at iPhone width.
- [ ] Test question page fits without text overlap.
- [ ] Learning question page fits without text overlap.
- [ ] Result pages fit without horizontal scrolling.
- [ ] Mobile app login/signup works with the same web account.
- [ ] Mobile app can fetch dashboard data after login.
- [ ] Mobile app handles API errors without blank pages.

## 9. Production Stability

- [ ] Render deploy completes successfully.
- [ ] Production app opens `/dashboard`, `/test`, `/learning`, `/statistics`, `/teacher`, and `/admin`.
- [ ] Persistent database path is set correctly on Render.
- [ ] Required environment variables are set:
  - [ ] `OPENAI_API_KEY`
  - [ ] `ASSEMBLYAI_API_KEY` if pronunciation fallback is enabled
  - [ ] `GEMINI_API_KEY` if sentence fallback is enabled
  - [ ] `TEACHER_INVITE_CODE` or `TEACHER_INVITE_CODES`
  - [ ] `ADMIN_EMAILS`
- [ ] AI quota/fallback errors are logged but do not break the user flow.
- [ ] Memory usage remains stable during a full 100-question level test.

## 10. Launch Decision

- [ ] No blocker bugs remain.
- [ ] Student test account completes Test -> Learning -> Review.
- [ ] Teacher test account completes Class -> Assignment -> Report.
- [ ] Admin account can verify usage records.
- [ ] Mobile daily-use path is acceptable.
- [ ] Copywriting on the main student and teacher pages is ready for public users.
