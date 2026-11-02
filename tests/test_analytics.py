import pytest
from trust_engine.analytics import validate_read_only_sql

def test_select_is_allowed_and_allowlisted():
    assert validate_read_only_sql("SELECT PARTNER_ID FROM CORE.TRANSACTIONS",
                                  {"CORE.TRANSACTIONS"}).startswith("SELECT")

@pytest.mark.parametrize("sql",["DELETE FROM CORE.TRANSACTIONS",
 "SELECT 1; DROP TABLE CORE.TRANSACTIONS","SELECT 1 -- bypass",
 "UPDATE CORE.TRANSACTIONS SET AMOUNT=0","CALL CORE.LOAD_TRANSACTIONS()"])
def test_mutating_or_multi_statement_sql_is_rejected(sql):
    with pytest.raises(ValueError):
        validate_read_only_sql(sql)

def test_non_allowlisted_object_is_rejected():
    with pytest.raises(ValueError):
        validate_read_only_sql("SELECT * FROM SECRET.TABLE",{"CORE.TRANSACTIONS"})
