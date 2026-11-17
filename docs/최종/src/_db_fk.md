외래키 84개 중 한 칼럼짜리 83개를 **부모 테이블(들어가는 곳)** 별로 묶었습니다. 나머지 1개는 두 칼럼짜리 `interview_question (parent_question_id, session_id) → interview_question (id, session_id)`로, 꼬리·재질문이 **같은 응시 안의** 질문만 가리키게 막습니다.  '자식.칼럼'이 '부모.칼럼'을 가리키고, 조인할 때는 `자식.칼럼 = 부모.칼럼`으로 잇습니다. **6.1**은 면접 파트가 만든 테이블입니다.

## application 로 들어오는 연결 (18개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `ai_error_alert.application_id` **6.1** | `application.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 알림이 걸린 지원 건 |
| `ai_usage_log.application_id` | `application.id` | 1 : N | 예 | NULL로 비움 | 어느 지원 건의 것인지 |
| `answer_accommodation.application_id` **6.1** | `application.id` | 1 : 1 | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원 건의 것인지 |
| `application_stage.application_id` **6.1** | `application.id` | 1 : 1 | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원 건의 것인지 |
| `application_stage_log.application_id` **6.1** | `application.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원 건의 것인지 |
| `coding_session.application_id` | `application.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원 건의 것인지 |
| `data_request.application_id` | `application.id` | 1 : N | 예 | NULL로 비움 | 어느 지원 건의 것인지 |
| `dept_opinion.application_id` | `application.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원 건의 것인지 |
| `document_evaluation.application_id` | `application.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원 건의 것인지 |
| `document_review.application_id` | `application.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원 건의 것인지 |
| `inquiry.application_id` | `application.id` | 1 : N | 예 | NULL로 비움 | 어느 지원 건의 것인지 |
| `interview_session.application_id` **6.1** | `application.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 어느 지원 건의 응시인지 (지원 건당 최대 3차) |
| `llm_call.application_id` **6.1** | `application.id` | 1 : N | 예 | 같이 삭제 (CASCADE) | 어느 지원 건을 위한 호출인지 |
| `prepared_question.application_id` **6.1** | `application.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원 건을 위해 미리 만든 질문인지 |
| `stage2_exception.application_id` | `application.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원 건의 것인지 |
| `stage2_score.application_id` | `application.id` | 1 : 1 | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원 건의 것인지 |
| `stage_result.application_id` | `application.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원 건의 것인지 |
| `suspicion_case.application_id` **6.1** | `application.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 어느 지원 건의 것인지 |

## interview_session 로 들어오는 연결 (8개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `identity_check.session_id` **6.1** | `interview_session.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 응시의 기록인지 |
| `interview_evaluation.session_id` **6.1** | `interview_session.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 응시의 최종 평가인지 (버전 1·2) |
| `interview_incident.session_id` **6.1** | `interview_session.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 응시의 기록인지 |
| `interview_note.session_id` **6.1** | `interview_session.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 응시의 기록인지 |
| `interview_question.session_id` **6.1** | `interview_session.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 응시의 기록인지 |
| `llm_call.session_id` **6.1** | `interview_session.id` | 1 : N | 예 | 같이 삭제 (CASCADE) | 면접 중 호출이면 그 응시 |
| `proctor_event.session_id` **6.1** | `interview_session.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 응시의 기록인지 |
| `suspicion_case.interview_session_id` **6.1** | `interview_session.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 면접 중 생긴 의심 건이면 그 응시 |

## interview_question 로 들어오는 연결 (2개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `interview_answer.question_id` **6.1** | `interview_question.id` | 1 : 1 | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 질문의 답변인지 (질문당 1개, 재녹음 불가) |
| `proctor_event.question_id` **6.1** | `interview_question.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 감독 이벤트가 생긴 문항 |

## interview_answer 로 들어오는 연결 (2개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `answer_judgement.answer_id` **6.1** | `interview_answer.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 답변의 판정인지 (다시 판정하면 새 행, 현재 판정은 1개) |
| `answer_signal.answer_id` **6.1** | `interview_answer.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 답변의 표정·목소리 구간인지 |

## interview_evaluation 로 들어오는 연결 (2개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `ai_error_alert.interview_evaluation_id` **6.1** | `interview_evaluation.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 재평가까지 실패한 평가 |
| `evaluation_check.evaluation_id` **6.1** | `interview_evaluation.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 평가 버전의 5검사인지 |

## job_posting 로 들어오는 연결 (8개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `announcement.posting_id` | `job_posting.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 어느 공고의 것인지 |
| `application.posting_id` | `job_posting.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 어느 공고의 것인지 |
| `coding_setting.posting_id` | `job_posting.id` | 1 : 1 | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 공고의 것인지 |
| `document_criteria.posting_id` | `job_posting.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 공고의 것인지 |
| `interview_setting.posting_id` **6.1** | `job_posting.id` | 1 : 1 | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 어느 공고의 면접 설정인지 (공고와 1 : 1) |
| `posting_assignee.posting_id` | `job_posting.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 공고의 것인지 |
| `posting_history.posting_id` | `job_posting.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 공고의 것인지 |
| `posting_review.posting_id` | `job_posting.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 공고의 것인지 |

## candidate 로 들어오는 연결 (8개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `application.candidate_id` | `candidate.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 어느 지원자의 것인지 |
| `candidate_consent.candidate_id` | `candidate.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원자의 것인지 |
| `candidate_social_account.candidate_id` | `candidate.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원자의 것인지 |
| `data_request.candidate_id` | `candidate.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 어느 지원자의 것인지 |
| `inquiry.candidate_id` | `candidate.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원자의 것인지 |
| `notification.candidate_id` | `candidate.id` | 1 : N | 예 | 같이 삭제 (CASCADE) | 어느 지원자의 것인지 |
| `notification_pref.candidate_id` | `candidate.id` | 1 : 1 | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원자의 것인지 |
| `resume.candidate_id` | `candidate.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 지원자의 것인지 |

## coding_session 로 들어오는 연결 (3개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `coding_attempt.session_id` | `coding_session.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 코딩 응시의 것인지 |
| `coding_result.session_id` | `coding_session.id` | 1 : 1 | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 코딩 응시의 것인지 |
| `interview_session.coding_session_id` **6.1** | `coding_session.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 3번 질문에 쓸 코딩 응시 (비개발 직군은 비어 있음) |

## question_bank 로 들어오는 연결 (1개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `prepared_question.bank_id` **6.1** | `question_bank.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 질문 은행에서 꺼낸 질문이면 그 은행 질문 |

## admin_user 로 들어오는 연결 (22개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `ai_error_alert.handled_by` **6.1** | `admin_user.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `announcement.checked_by` | `admin_user.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `announcement.published_by` | `admin_user.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `answer_accommodation.decided_by` **6.1** | `admin_user.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `data_request.handled_by` | `admin_user.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `dept_opinion.author_id` | `admin_user.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `document_review.reviewer_id` | `admin_user.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `hiring_request.handled_by` | `admin_user.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `hiring_request.requested_by` | `admin_user.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `inquiry.answered_by` | `admin_user.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `interview_evaluation.confirmed_by` **6.1** | `admin_user.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `interview_note.author_id` **6.1** | `admin_user.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `job_posting.created_by` | `admin_user.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `notice.created_by` | `admin_user.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `notification.admin_user_id` | `admin_user.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `policy_setting.updated_by` | `admin_user.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `posting_assignee.admin_user_id` | `admin_user.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `posting_history.changed_by` | `admin_user.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `posting_review.reviewer_id` | `admin_user.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `stage2_exception.approved_by` | `admin_user.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `stage_result.decided_by` | `admin_user.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |
| `suspicion_case.decided_by` **6.1** | `admin_user.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 처리·작성한 관리자 |

## announcement 로 들어오는 연결 (1개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `notification.announcement_id` | `announcement.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 어느 발표의 알림인지 |

## coding_attempt 로 들어오는 연결 (2개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `coding_review.attempt_id` | `coding_attempt.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 문제 풀이의 것인지 |
| `coding_submission.attempt_id` | `coding_attempt.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 문제 풀이의 것인지 |

## coding_problem 로 들어오는 연결 (2개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `coding_attempt.problem_id` | `coding_problem.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 푼 문제 |
| `coding_case.problem_id` | `coding_problem.id` | 1 : N | 아니요 (필수) | 같이 삭제 (CASCADE) | 어느 문제의 것인지 |

## consent_document 로 들어오는 연결 (1개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `candidate_consent.consent_document_id` | `consent_document.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 어느 동의서 버전에 동의했는지 |

## department 로 들어오는 연결 (2개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `admin_user.department_id` | `department.id` | 1 : N | 예 | 막음 (자식이 있으면 지울 수 없음) | 어느 부서인지 |
| `hiring_request.department_id` | `department.id` | 1 : N | 아니요 (필수) | 막음 (자식이 있으면 지울 수 없음) | 어느 부서인지 |

## hiring_request 로 들어오는 연결 (1개)

| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |
|---|---|---|---|---|---|
| `job_posting.hiring_request_id` | `hiring_request.id` | 1 : 1 | 예 | 막음 (자식이 있으면 지울 수 없음) | 부서 채용 요청에서 만든 공고면 그 요청 |
