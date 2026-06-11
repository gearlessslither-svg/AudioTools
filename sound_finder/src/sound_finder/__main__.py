import sys

from .app import main
from .current_test import seed_current_test
from .handoff import CURRENT_PLAN_PATH, write_plan_file
from .local_llm import config_from_mapping, generate_requirement_plan
from .maintenance import benchmark_search
from .maintenance import database_status
from .maintenance import rebuild_fts


def _value_after(flag: str) -> str:
    try:
        index = sys.argv.index(flag)
    except ValueError:
        return ""
    if index + 1 >= len(sys.argv):
        return ""
    return sys.argv[index + 1]


def _flag_present(*flags: str) -> bool:
    return any(flag in sys.argv for flag in flags)


def _local_model_config_from_args():
    return config_from_mapping(
        {
            "mode": _value_after("--llm-mode"),
            "provider": _value_after("--local-provider"),
            "base_url": _value_after("--local-base-url"),
            "model": _value_after("--local-model"),
            "api_key": _value_after("--local-api-key"),
            "remote_base_url": _value_after("--remote-base-url"),
            "remote_model": _value_after("--remote-model"),
            "remote_api_key": _value_after("--remote-api-key"),
            "remote_slow_ms": _value_after("--remote-slow-ms"),
            "temperature": _value_after("--local-temperature"),
            "timeout": _value_after("--local-timeout"),
            "max_categories": _value_after("--local-max-categories"),
            "allow_rule_fallback": "1" if _flag_present("--local-rule-fallback") else "",
        }
    )


def generate_local_plan_file() -> None:
    requirement = _value_after("--generate-local-plan")
    if not requirement and not sys.stdin.isatty():
        requirement = sys.stdin.read().strip()
    if not requirement:
        raise SystemExit("Missing requirement. Use --generate-local-plan \"...\" or pipe text to stdin.")
    generated = generate_requirement_plan(requirement, _local_model_config_from_args())
    write_plan_file(CURRENT_PLAN_PATH, generated.title, generated.requirement, generated.categories)
    warning = f"\nwarning: {generated.warning}" if generated.warning else ""
    print(
        f"wrote: {CURRENT_PLAN_PATH}\n"
        f"title: {generated.title}\n"
        f"source: {generated.source}\n"
        f"categories: {len(generated.categories)}"
        f"{warning}"
    )


if __name__ == "__main__":
    if "--seed-current-test" in sys.argv:
        session_id = seed_current_test()
        print(f"Seeded current UI-button test session: {session_id}")
    elif "--generate-local-plan" in sys.argv:
        generate_local_plan_file()
    elif "--db-status" in sys.argv:
        print(database_status())
    elif "--rebuild-fts" in sys.argv:
        print(rebuild_fts())
    elif "--benchmark-search" in sys.argv:
        raw_queries = _value_after("--benchmark-search")
        queries = [query.strip() for query in raw_queries.split(";") if query.strip()] if raw_queries else None
        print(benchmark_search(queries))
    else:
        main()
