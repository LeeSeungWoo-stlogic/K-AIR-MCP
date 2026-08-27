from app.main import mcp


def test_official_mcp_tools_registered():
    names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert names == {
        "list_tables",
        "describe_table",
        "get_distinct_values",
        "query_table",
        "aggregate_table",
    }
