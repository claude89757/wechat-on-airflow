from pathlib import Path

R=Path(__file__).resolve().parents[1]

p=R/'webapp/wrangler.jsonc'; t=p.read_text()
old='''    "STANDARD_DAILY_EMAIL_LIMIT": "30",\n    "PRIORITY_DAILY_EMAIL_LIMIT": "100"'''
new='''    "STANDARD_DAILY_EMAIL_LIMIT": "30",\n    "PRIORITY_DAILY_EMAIL_LIMIT": "100",\n    "STANDARD_ACTIVE_SUBSCRIPTION_LIMIT": "5",\n    "PRIORITY_ACTIVE_SUBSCRIPTION_LIMIT": "20"'''
if t.count(old)!=1: raise SystemExit('wrangler limit vars not matched')
p.write_text(t.replace(old,new,1))

(R/'.github/workflows/ops-chatops.yml').write_text(r'''name: Production Ops ChatOps
run-name: ops-chatops/${{ github.event.comment.id }}

on:
  issue_comment:
    types: [created]

permissions:
  checks: read
  contents: read
  issues: write

concurrency:
  group: production-ops-chatops
  cancel-in-progress: false

jobs:
  parse:
    if: >-
      github.event.issue.number == 39 &&
      github.event.comment.user.login == github.repository_owner &&
      startsWith(github.event.comment.body, '/ops ')
    runs-on: ubuntu-latest
    outputs:
      operation: ${{ steps.command.outputs.operation }}
      target_commit: ${{ steps.command.outputs.target_commit }}
    steps:
      - name: Parse exact ops command
        id: command
        shell: bash
        env:
          OPS_COMMAND: ${{ github.event.comment.body }}
        run: |
          set -euo pipefail
          pattern='^/ops (webapp-observation-diagnose|priority-invite-create) ([0-9A-Fa-f]{40})$'
          if [[ ! "$OPS_COMMAND" =~ $pattern ]]; then
            echo 'Expected: /ops <webapp-observation-diagnose|priority-invite-create> <40-char-sha>' >&2
            exit 2
          fi
          command="${BASH_REMATCH[1]}"
          target_commit="${BASH_REMATCH[2],,}"
          case "$command" in
            webapp-observation-diagnose) operation=webapp_observation_diagnose ;;
            priority-invite-create) operation=priority_invite_create ;;
            *) exit 2 ;;
          esac
          { echo "operation=$operation"; echo "target_commit=$target_commit"; } >> "$GITHUB_OUTPUT"
      - name: Wait for main CI verify
        env:
          GH_TOKEN: ${{ github.token }}
          TARGET_COMMIT: ${{ steps.command.outputs.target_commit }}
        run: |
          set -euo pipefail
          deadline=$((SECONDS + 1800))
          while (( SECONDS < deadline )); do
            result="$(gh api "repos/$GITHUB_REPOSITORY/commits/$TARGET_COMMIT/check-runs" --jq '[.check_runs[] | select(.name == "verify")] | sort_by(.started_at) | last | [.status, (.conclusion // "")] | @tsv' 2>/dev/null || true)"
            if [[ "$result" == $'completed\tsuccess' ]]; then exit 0; fi
            if [[ "$result" == completed$'\t'* && "$result" != $'completed\tsuccess' ]]; then exit 1; fi
            sleep 10
          done
          exit 1
      - name: Acknowledge operation
        env:
          GH_TOKEN: ${{ github.token }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
          OPERATION: ${{ steps.command.outputs.operation }}
          TARGET_COMMIT: ${{ steps.command.outputs.target_commit }}
          RUN_URL: https://github.com/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: gh issue comment "$ISSUE_NUMBER" --repo "$GITHUB_REPOSITORY" --body "Accepted protected operation \`$OPERATION\` for \`$TARGET_COMMIT\`. Run: $RUN_URL"

  operate:
    needs: parse
    uses: ./.github/workflows/production-airflow.yml
    with:
      operation: ${{ needs.parse.outputs.operation }}
      target_commit: ${{ needs.parse.outputs.target_commit }}
      request_id: ops-${{ github.run_id }}
      confirm_real_send: false
      probe_target_membership: all
    secrets: inherit

  report:
    if: always() && needs.parse.result != 'skipped'
    needs: [parse, operate]
    runs-on: ubuntu-latest
    steps:
      - name: Report operation result
        env:
          GH_TOKEN: ${{ github.token }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
          OPERATION: ${{ needs.parse.outputs.operation }}
          TARGET_COMMIT: ${{ needs.parse.outputs.target_commit }}
          RESULT: ${{ needs.operate.result }}
          RUN_URL: https://github.com/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: |
          gh issue comment "$ISSUE_NUMBER" --repo "$GITHUB_REPOSITORY" --body "Protected operation \`$OPERATION\` for \`$TARGET_COMMIT\`: \`$RESULT\`. Run: $RUN_URL"
          test "$RESULT" = success
''')

p=R/'.github/workflows/production-airflow.yml'; t=p.read_text()
old='''          - phone_diagnose\n          - webapp_observation_diagnose'''; new='''          - phone_diagnose\n          - priority_invite_create\n          - webapp_observation_diagnose'''
if t.count(old)!=1: raise SystemExit('airflow options not matched')
t=t.replace(old,new,1)
old='''            phone_diagnose)\n              PYTHONPATH=src python scripts/diagnose_zacks_phone.py --format json\n              ;;\n            webapp_observation_diagnose)'''; new='''            phone_diagnose)\n              PYTHONPATH=src python scripts/diagnose_zacks_phone.py --format json\n              ;;\n            priority_invite_create)\n              bash scripts/create_priority_invite.sh\n              ;;\n            webapp_observation_diagnose)'''
if t.count(old)!=1: raise SystemExit('airflow case not matched')
t=t.replace(old,new,1)
if 'Upload protected priority invite' not in t:
    t=t.rstrip()+r'''
      - name: Upload protected priority invite
        if: inputs.operation == 'priority_invite_create'
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        with:
          name: priority-invite-${{ inputs.request_id }}
          path: .local/diagnostics/priority-invite.json
          if-no-files-found: error
          retention-days: 1
'''
p.write_text(t)
print('ops patched')