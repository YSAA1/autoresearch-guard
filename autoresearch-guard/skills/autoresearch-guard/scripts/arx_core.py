from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 3
VERIFICATION_SCHEMA_VERSION = 1
SESSION_STATES = {"active", "paused", "finished"}
VERDICTS = {"pass", "fail", "unknown"}
OUTCOMES = {"verified", "unverified", "inconclusive", "stopped", "blocked"}
CONTRACT_FIELDS = {"claim", "checks"}
CHECK_FIELDS = {"id", "criterion", "method", "evidence_required"}


class ArxError(RuntimeError):
    exit_code = 2


class ArxUsageError(ArxError):
    """A caller supplied an invalid command, transition, or verified claim."""


class ArxIoError(ArxError):
    """The on-disk state is corrupt or a durable write could not complete."""

    exit_code = 1


_LOCK_STATE = threading.local()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def research_root_for(cwd: str | Path | None = None) -> Path:
    directory = (Path.cwd() if cwd is None else Path(cwd)).expanduser().resolve()
    for candidate_directory in (directory, *directory.parents):
        candidate = candidate_directory / ".research"
        if candidate.is_dir():
            return candidate
    return directory / ".research"


def current_dir(root: str | Path) -> Path:
    return Path(root).expanduser().resolve() / "current"


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _lock_depths() -> dict[str, int]:
    depths = getattr(_LOCK_STATE, "depths", None)
    if depths is None:
        depths = {}
        _LOCK_STATE.depths = depths
    return depths


@contextmanager
def research_lock(root: str | Path) -> Iterator[None]:
    """Serialize mutations for one research root across processes."""

    root_path = Path(root).expanduser().resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    lock_path = root_path / ".arx.lock"
    key = str(lock_path)
    depths = _lock_depths()
    if depths.get(key, 0):
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
        return

    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            if lock_path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        depths[key] = 1
        try:
            yield
        finally:
            depths.pop(key, None)
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise ArxIoError(f"无法安全写入 {path}: {exc}") from exc
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path, description: str, *, error_type: type[ArxError] = ArxIoError) -> dict[str, Any]:
    if not path.exists():
        raise error_type(f"缺少{description}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise error_type(f"无法读取{description}: {path}") from exc
    if not isinstance(value, dict):
        raise error_type(f"{description}必须是 JSON 对象: {path}")
    return value


def _nonempty(value: Any, name: str, *, error_type: type[ArxError] = ArxUsageError) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{name}不能为空")
    return value.strip()


def _verification_path(root: Path, version: int) -> Path:
    return current_dir(root) / "verifications" / f"v{version:03d}.json"


def _session_path(root: Path) -> Path:
    return current_dir(root) / "session.json"


def normalize_contract(value: Any, *, error_type: type[ArxError] = ArxUsageError) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != CONTRACT_FIELDS:
        raise error_type("验证契约只能包含 claim 和 checks")
    claim = _nonempty(value.get("claim"), "claim", error_type=error_type)
    raw_checks = value.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise error_type("checks 必须是非空数组")

    checks: list[dict[str, str]] = []
    ids: set[str] = set()
    for index, raw_check in enumerate(raw_checks, 1):
        if not isinstance(raw_check, dict) or set(raw_check) != CHECK_FIELDS:
            raise error_type(f"第 {index} 条检查只能包含 id、criterion、method 和 evidence_required")
        check = {
            "id": _nonempty(raw_check.get("id"), f"第 {index} 条检查的 id", error_type=error_type),
            "criterion": _nonempty(raw_check.get("criterion"), f"第 {index} 条检查的 criterion", error_type=error_type),
            "method": _nonempty(raw_check.get("method"), f"第 {index} 条检查的 method", error_type=error_type),
            "evidence_required": _nonempty(
                raw_check.get("evidence_required"),
                f"第 {index} 条检查的 evidence_required",
                error_type=error_type,
            ),
        }
        if check["id"] in ids:
            raise error_type(f"检查 id 重复: {check['id']}")
        ids.add(check["id"])
        checks.append(check)
    return {"claim": claim, "checks": checks}


def _load_contract_file(path_text: str) -> dict[str, Any]:
    path = Path(path_text).expanduser().resolve()
    try:
        raw = _read_json(path, "验证契约文件", error_type=ArxUsageError)
    except ArxUsageError:
        raise
    return normalize_contract(raw)


def _validate_session(session: dict[str, Any]) -> dict[str, Any]:
    if session.get("schema_version") != SCHEMA_VERSION:
        raise ArxIoError("session.json 的 schema_version 不受支持")
    _nonempty(session.get("session_id"), "session_id", error_type=ArxIoError)
    _nonempty(session.get("goal"), "goal", error_type=ArxIoError)
    if session.get("status") not in SESSION_STATES:
        raise ArxIoError("session.json 的 status 无效")
    version = session.get("current_verification_version")
    if version is not None and (not isinstance(version, int) or version < 1):
        raise ArxIoError("session.json 的 current_verification_version 无效")
    if not isinstance(session.get("contract_digest"), str):
        raise ArxIoError("session.json 的 contract_digest 无效")
    return session


def _load_session(root: Path) -> dict[str, Any]:
    current = current_dir(root)
    if not current.exists():
        raise ArxUsageError("没有进行中的研究；先运行 arx start")
    if (current / "state.yaml").exists():
        raise ArxUsageError("检测到旧 state.yaml；请使用 arx start --archive-legacy 原样归档")
    return _validate_session(_read_json(_session_path(root), "session.json"))


def _result_base(check_id: str, verdict: str, evidence: list[str], reason: str, contract_digest: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "verdict": verdict,
        "evidence": evidence,
        "reason": reason,
        "contract_digest": contract_digest,
    }


def _load_verification(root: Path, session: dict[str, Any]) -> dict[str, Any] | None:
    version = session.get("current_verification_version")
    if version is None:
        return None
    if not isinstance(version, int):
        raise ArxIoError("当前验证版本无效")
    verification = _read_json(_verification_path(root, version), f"验证文件 v{version:03d}")
    if verification.get("schema_version") != VERIFICATION_SCHEMA_VERSION or verification.get("version") != version:
        raise ArxIoError("验证文件版本不一致")
    contract = normalize_contract(verification.get("contract"), error_type=ArxIoError)
    digest = _digest(contract)
    if verification.get("contract_digest") != digest or session.get("contract_digest") != digest:
        raise ArxIoError("锁定验证契约的摘要已漂移")
    results = verification.get("results")
    if not isinstance(results, list):
        raise ArxIoError("验证结果必须是数组")
    check_ids = {check["id"] for check in contract["checks"]}
    for index, result in enumerate(results, 1):
        if not isinstance(result, dict):
            raise ArxIoError(f"第 {index} 条验证结果无效")
        try:
            check_id = _nonempty(result.get("check_id"), "check_id", error_type=ArxIoError)
            verdict = _nonempty(result.get("verdict"), "verdict", error_type=ArxIoError)
            reason = _nonempty(result.get("reason"), "reason", error_type=ArxIoError)
        except ArxIoError:
            raise ArxIoError(f"第 {index} 条验证结果字段无效") from None
        evidence = result.get("evidence")
        if check_id not in check_ids or verdict not in VERDICTS or not isinstance(evidence, list):
            raise ArxIoError(f"第 {index} 条验证结果不匹配当前契约")
        clean_evidence = [_nonempty(item, "evidence", error_type=ArxIoError) for item in evidence]
        if verdict == "pass" and not clean_evidence:
            raise ArxIoError(f"第 {index} 条通过结果缺少证据")
        base = _result_base(check_id, verdict, clean_evidence, reason, digest)
        if result.get("contract_digest") != digest or result.get("record_digest") != _digest(base):
            raise ArxIoError(f"第 {index} 条验证结果的绑定摘要无效")
    return verification


def _latest_results(verification: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for result in verification["results"]:
        latest[result["check_id"]] = result
    return latest


def _empty_verification() -> dict[str, Any]:
    return {"locked": False, "version": None, "contract_digest": "", "checks": []}


def _verification_status(verification: dict[str, Any] | None) -> tuple[dict[str, Any], bool, list[str]]:
    if verification is None:
        return _empty_verification(), False, ["尚未锁定验证契约。"]
    latest = _latest_results(verification)
    checks = []
    reasons: list[str] = []
    for check in verification["contract"]["checks"]:
        result = latest.get(check["id"])
        verdict = result.get("verdict") if result else None
        checks.append({"id": check["id"], "verdict": verdict})
        if verdict != "pass":
            if verdict is None:
                reasons.append(f"检查 {check['id']} 尚未记录结果。")
            else:
                reasons.append(f"检查 {check['id']} 的最新结果为 {verdict}。")
    return (
        {
            "locked": True,
            "version": verification["version"],
            "contract_digest": verification["contract_digest"],
            "checks": checks,
        },
        not reasons,
        reasons,
    )


def status_report(root: str | Path) -> tuple[dict[str, Any], int]:
    """Read status without creating files or acquiring a write lock."""

    root_path = Path(root).expanduser().resolve()
    current = current_dir(root_path)
    if not current.exists():
        return (
            {
                "state": "idle",
                "session": None,
                "verification": _empty_verification(),
                "can_finish_verified": False,
                "reasons": ["没有进行中的研究。"],
                "next_actions": ["arx start --goal TEXT"],
            },
            0,
        )
    if (current / "state.yaml").exists():
        return (
            {
                "state": "legacy",
                "session": None,
                "verification": _empty_verification(),
                "can_finish_verified": False,
                "reasons": ["检测到旧 state.yaml；新 CLI 不会迁移它。"],
                "next_actions": ["arx start --goal TEXT --archive-legacy"],
            },
            0,
        )
    try:
        session = _load_session(root_path)
    except ArxError as exc:
        return (
            {
                "state": "corrupt",
                "session": None,
                "verification": _empty_verification(),
                "can_finish_verified": False,
                "reasons": [str(exc)],
                "next_actions": ["检查 .research/current/session.json 后重试。"],
            },
            1,
        )
    try:
        verification, can_finish, reasons = _verification_status(_load_verification(root_path, session))
    except ArxIoError as exc:
        verification = {
            "locked": session["current_verification_version"] is not None,
            "version": session["current_verification_version"],
            "contract_digest": session["contract_digest"],
            "checks": [],
        }
        can_finish = False
        reasons = [str(exc)]
        status_code = 1
    else:
        status_code = 0

    state = str(session["status"])
    if state == "paused":
        pause_reason = str(session.get("pause_reason") or "未说明")
        reasons = [f"研究已暂停：{pause_reason}", *reasons]
        next_actions = ["arx resume", "arx finish --outcome OUTCOME --summary TEXT"]
    elif verification["locked"]:
        next_actions = ["arx verify record --check ID --verdict pass|fail|unknown --reason TEXT"]
        next_actions.append("arx finish --outcome verified --summary TEXT" if can_finish else "arx finish --outcome unverified --summary TEXT")
    else:
        next_actions = ["arx verify lock --file FILE", "arx finish --outcome unverified --summary TEXT"]

    return (
        {
            "state": state,
            "session": session,
            "verification": verification,
            "can_finish_verified": can_finish,
            "reasons": reasons,
            "next_actions": next_actions,
        },
        status_code,
    )


def _archive_destination(root: Path, identifier: str) -> Path:
    archive_root = root / "archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_identifier = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in identifier)
    candidate = archive_root / f"{stamp}-{safe_identifier or 'session'}"
    suffix = 2
    while candidate.exists():
        candidate = archive_root / f"{stamp}-{safe_identifier or 'session'}-{suffix}"
        suffix += 1
    return candidate


def _move_current_to_archive(root: Path, identifier: str, legacy_manifest: dict[str, Any] | None = None) -> Path:
    source = current_dir(root)
    destination = _archive_destination(root, identifier)
    moved = False
    try:
        os.replace(source, destination)
        moved = True
        _fsync_directory(root)
        _fsync_directory(destination.parent)
        if legacy_manifest is not None:
            _write_json(destination / "legacy-manifest.json", legacy_manifest)
        return destination
    except (OSError, ArxIoError) as exc:
        if moved and destination.exists() and not source.exists():
            try:
                os.replace(destination, source)
                _fsync_directory(root)
            except OSError as rollback_error:
                raise ArxIoError(f"归档失败且无法恢复 current: {rollback_error}") from exc
        if isinstance(exc, ArxIoError):
            raise
        raise ArxIoError(f"无法归档 current: {exc}") from exc


def _new_session(goal: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": f"s-{uuid.uuid4().hex[:12]}",
        "goal": goal,
        "status": "active",
        "current_verification_version": None,
        "contract_digest": "",
        "created_at": now,
        "updated_at": now,
        "pause_reason": "",
        "finished_at": "",
        "outcome": None,
        "summary": "",
    }


def start_session(root: str | Path, goal: str, *, archive_legacy: bool = False) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    clean_goal = _nonempty(goal, "goal")
    with research_lock(root_path):
        current = current_dir(root_path)
        if current.exists():
            if (current / "state.yaml").exists() and archive_legacy:
                manifest = {
                    "schema_version": 1,
                    "kind": "legacy",
                    "archived_at": utc_now(),
                    "reason": "start --archive-legacy",
                }
                _move_current_to_archive(root_path, "legacy", manifest)
            elif (current / "state.yaml").exists():
                raise ArxUsageError("检测到旧 state.yaml；请显式使用 --archive-legacy")
            else:
                raise ArxUsageError("已有活动研究，不能用 start 覆盖")
        current.mkdir(parents=True, exist_ok=False)
        (current / "verifications").mkdir()
        session = _new_session(clean_goal)
        _write_json(_session_path(root_path), session)
        return session


def lock_contract(root: str | Path, contract_file: str, *, revise: bool = False) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    contract = _load_contract_file(contract_file)
    digest = _digest(contract)
    with research_lock(root_path):
        session = _load_session(root_path)
        if session["status"] not in {"active", "paused"}:
            raise ArxUsageError("已结束的研究不能锁定验证契约")
        previous = _load_verification(root_path, session)
        previous_version = session["current_verification_version"]
        if previous is None:
            if revise:
                raise ArxUsageError("尚无验证契约，不能使用 --revise")
            version = 1
        else:
            if not revise:
                raise ArxUsageError("已有锁定验证契约；修改时请使用 --revise")
            version = int(previous_version) + 1
        verification: dict[str, Any] = {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "version": version,
            "contract": contract,
            "contract_digest": digest,
            "locked_at": utc_now(),
            "results": [],
        }
        if previous_version is not None:
            verification["supersedes"] = previous_version
        _write_json(_verification_path(root_path, version), verification)
        session["current_verification_version"] = version
        session["contract_digest"] = digest
        session["updated_at"] = utc_now()
        _write_json(_session_path(root_path), session)
        return verification


def record_result(
    root: str | Path,
    check_id: str,
    verdict: str,
    evidence: list[str],
    reason: str,
) -> bool:
    root_path = Path(root).expanduser().resolve()
    clean_check_id = _nonempty(check_id, "check")
    clean_verdict = _nonempty(verdict, "verdict")
    if clean_verdict not in VERDICTS:
        raise ArxUsageError("verdict 必须是 pass、fail 或 unknown")
    clean_reason = _nonempty(reason, "reason")
    clean_evidence = [_nonempty(item, "evidence") for item in evidence]
    if clean_verdict == "pass" and not clean_evidence:
        raise ArxUsageError("pass 结果至少需要一条 evidence")
    with research_lock(root_path):
        session = _load_session(root_path)
        if session["status"] != "active":
            raise ArxUsageError("只有 active 研究可以记录验证结果")
        verification = _load_verification(root_path, session)
        if verification is None:
            raise ArxUsageError("尚未锁定验证契约")
        check_ids = {check["id"] for check in verification["contract"]["checks"]}
        if clean_check_id not in check_ids:
            raise ArxUsageError(f"未知的检查 id: {clean_check_id}")
        base = _result_base(
            clean_check_id,
            clean_verdict,
            clean_evidence,
            clean_reason,
            verification["contract_digest"],
        )
        record_digest = _digest(base)
        if any(result.get("record_digest") == record_digest for result in verification["results"]):
            return False
        verification["results"].append({**base, "record_digest": record_digest, "recorded_at": utc_now()})
        _write_json(_verification_path(root_path, verification["version"]), verification)
        return True


def pause_session(root: str | Path, reason: str) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    clean_reason = _nonempty(reason, "reason")
    with research_lock(root_path):
        session = _load_session(root_path)
        if session["status"] != "active":
            raise ArxUsageError("只有 active 研究可以暂停")
        session["status"] = "paused"
        session["pause_reason"] = clean_reason
        session["updated_at"] = utc_now()
        _write_json(_session_path(root_path), session)
        return session


def resume_session(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    with research_lock(root_path):
        session = _load_session(root_path)
        if session["status"] != "paused":
            raise ArxUsageError("只有 paused 研究可以恢复")
        session["status"] = "active"
        session["pause_reason"] = ""
        session["updated_at"] = utc_now()
        _write_json(_session_path(root_path), session)
        return session


def _require_verified(root: Path, session: dict[str, Any]) -> None:
    verification = _load_verification(root, session)
    if verification is None:
        raise ArxUsageError("verified 收口需要先锁定验证契约")
    _status, can_finish, reasons = _verification_status(verification)
    if not can_finish:
        raise ArxUsageError("不能以 verified 收口：" + " ".join(reasons))


def finish_session(root: str | Path, outcome: str, summary: str) -> Path:
    root_path = Path(root).expanduser().resolve()
    clean_outcome = _nonempty(outcome, "outcome")
    if clean_outcome not in OUTCOMES:
        raise ArxUsageError("outcome 无效")
    clean_summary = _nonempty(summary, "summary")
    with research_lock(root_path):
        session = _load_session(root_path)
        if session["status"] not in {"active", "paused"}:
            raise ArxUsageError("只有 active 或 paused 研究可以收口")
        if clean_outcome == "verified":
            _require_verified(root_path, session)
        previous = copy.deepcopy(session)
        session["status"] = "finished"
        session["finished_at"] = utc_now()
        session["outcome"] = clean_outcome
        session["summary"] = clean_summary
        session["updated_at"] = utc_now()
        _write_json(_session_path(root_path), session)
        try:
            return _move_current_to_archive(root_path, session["session_id"])
        except ArxIoError:
            try:
                _write_json(_session_path(root_path), previous)
            except ArxIoError as rollback_error:
                raise ArxIoError(f"归档失败，且无法恢复 finish 前状态: {rollback_error}") from rollback_error
            raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arx", description="AutoResearch 的最小状态与验证 CLI")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="开始一项研究")
    start.add_argument("--goal", required=True)
    start.add_argument("--archive-legacy", action="store_true")

    status = commands.add_parser("status", help="显示当前状态")
    status.add_argument("--json", action="store_true")

    verify = commands.add_parser("verify", help="锁定或记录验证")
    verify_commands = verify.add_subparsers(dest="verify_command", required=True)
    lock = verify_commands.add_parser("lock", help="锁定验证契约")
    lock.add_argument("--file", required=True)
    lock.add_argument("--revise", action="store_true")
    record = verify_commands.add_parser("record", help="记录验证结果")
    record.add_argument("--check", required=True)
    record.add_argument("--verdict", required=True, choices=sorted(VERDICTS))
    record.add_argument("--evidence", nargs="*", default=[])
    record.add_argument("--reason", required=True)

    pause = commands.add_parser("pause", help="暂停研究")
    pause.add_argument("--reason", required=True)
    commands.add_parser("resume", help="恢复研究")

    finish = commands.add_parser("finish", help="收口并归档研究")
    finish.add_argument("--outcome", required=True, choices=sorted(OUTCOMES))
    finish.add_argument("--summary", required=True)
    return parser


def _print_status(report: dict[str, Any]) -> None:
    session = report["session"] or {}
    print(f"state: {report['state']}")
    if session:
        print(f"goal: {session.get('goal')}")
    print(f"can_finish_verified: {report['can_finish_verified']}")
    for reason in report["reasons"]:
        print(f"- {reason}")
    for action in report["next_actions"]:
        print(f"next: {action}")


def cli_main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = research_root_for()
    try:
        if args.command == "start":
            session = start_session(root, args.goal, archive_legacy=args.archive_legacy)
            print(f"started: {session['session_id']}")
        elif args.command == "status":
            report, status_code = status_report(root)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            else:
                _print_status(report)
            return status_code
        elif args.command == "verify" and args.verify_command == "lock":
            verification = lock_contract(root, args.file, revise=args.revise)
            print(f"locked: v{verification['version']:03d}")
        elif args.command == "verify" and args.verify_command == "record":
            created = record_result(root, args.check, args.verdict, args.evidence, args.reason)
            print("recorded" if created else "no-op: identical result already recorded")
        elif args.command == "pause":
            pause_session(root, args.reason)
            print("paused")
        elif args.command == "resume":
            resume_session(root)
            print("resumed")
        elif args.command == "finish":
            archive = finish_session(root, args.outcome, args.summary)
            print(f"archived: {archive}")
        else:  # pragma: no cover - argparse makes this unreachable
            raise ArxUsageError("未知命令")
    except ArxError as exc:
        print(f"arx: {exc}", file=os.sys.stderr)
        return exc.exit_code
    return 0
