"""Check the UI documentation contract (P4)."""

from strength_coach.web import docs_audit


def main() -> int:
    findings = docs_audit.audit()
    if findings:
        for finding in findings:
            print(finding)
        return 1
    print(docs_audit.report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
