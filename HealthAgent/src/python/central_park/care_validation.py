"""Deterministic review-contract checks; clinical meaning is reviewed by the model."""


class CareValidationError(ValueError):
    def __init__(self, category, message, field=None):
        super().__init__(message)
        self.category = category
        self.field = field


class ReviewContractError(CareValidationError):
    def __init__(self, message):
        super().__init__('review_contract', message, 'review')


REVIEW_RULES = ('medication_scope', 'patient_facts', 'urgency', 'evidence_applicability')


def prose_fields(draft):
    yield 'title', draft.title
    for i, activity in enumerate(draft.activities):
        yield f'activities[{i}].description', activity.description
        if activity.timing:
            yield f'activities[{i}].timing', activity.timing
    for name in ('missing_information', 'uncovered_conditions', 'review_notes'):
        for i, value in enumerate(getattr(draft, name)):
            yield f'{name}[{i}]', value


def validate_review_contract(review, draft):
    """Verify coverage, decision consistency and evidence, not medical interpretation.

    A valid contract is necessary for a model decision, not proof that it is correct.
    Unsupported/malformed reviews are technical failures, never automatic approvals.
    """
    checks = review.checks.model_dump()
    fields = dict(prose_fields(draft))
    failed = {rule for rule, passed in checks.items() if not passed}
    cited = set()
    for issue in review.issues:
        if issue.field not in fields:
            raise ReviewContractError(f'Issue field {issue.field!r} is not a draft prose field; '
                                      'do not attribute input or application-owned text to the draft.')
        if not issue.quote.strip() or issue.quote not in fields[issue.field]:
            raise ReviewContractError(f'{issue.field}: issue.quote must be a contiguous, verbatim '
                                      'excerpt from that field, with no paraphrase or ellipsis.')
        if not issue.explanation.strip():
            raise ReviewContractError(f'{issue.field}: explain the violation of {issue.rule}.')
        cited.add(issue.rule)
    if failed != cited:
        raise ReviewContractError('Each failed check needs an evidenced issue; each issue must '
                                  'correspond to a failed check.')
    if review.approved != (not failed and not review.issues):
        raise ReviewContractError('approved must agree with checks and issues.')


def review_feedback(review):
    return 'Review rejected: ' + '; '.join(
        f'{issue.rule} at {issue.field}: {issue.explanation} '
        f'[draft quote: {issue.quote!r}]' for issue in review.issues)
