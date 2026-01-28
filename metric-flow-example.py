import sys
from pathlib import Path
from typing import Optional
import datetime

import pandas as pd
from pydantic import BaseModel

# dbt-metricflow's CLI infrastructure
from dbt_metricflow.cli.cli_configuration import CLIConfiguration
from metricflow.engine.metricflow_engine import (
    MetricFlowEngine,
    MetricFlowQueryRequest,
)
from metricflow.data_table.mf_table import MetricFlowDataTable


# =============================================================================
# Query Model
# =============================================================================

class Query(BaseModel):
    """Query parameters for MetricFlow."""
    
    metrics: list[str]
    group_by: list[str]
    where: Optional[list[str]] = None
    order_by: Optional[list[str]] = None
    limit: Optional[int] = None
    start_time: Optional[datetime.datetime] = None
    end_time: Optional[datetime.datetime] = None


# =============================================================================
# MetricFlow Client
# =============================================================================

class MetricFlow:
    """Python interface to MetricFlow."""
    
    def __init__(
        self,
        project_dir: Optional[str | Path] = None,
        profiles_dir: Optional[str | Path] = None,
    ):
        self._config = CLIConfiguration()
        project_path = Path(project_dir) if project_dir else None
        profiles_path = Path(profiles_dir) if profiles_dir else None
        
        self._config.setup(
            dbt_project_path=project_path,
            dbt_profiles_path=profiles_path,
            configure_file_logging=False,
        )
    
    @property
    def engine(self) -> MetricFlowEngine:
        return self._config.mf
    
    def list_metrics(self) -> list[str]:
        """List available metric names."""
        return [m.name for m in self.engine.list_metrics(include_dimensions=False)]
    
    def list_dimensions(self, metrics: Optional[list[str]] = None) -> list[str]:
        """List dimension names, optionally filtered by metrics."""
        return [d.dunder_name for d in self.engine.list_dimensions(metric_names=metrics)]
    
    def query(self, q: Query) -> pd.DataFrame:
        """Execute a query and return a pandas DataFrame."""
        request = MetricFlowQueryRequest.create_with_random_request_id(
            metric_names=q.metrics,
            group_by_names=q.group_by,
            where_constraints=q.where,
            order_by_names=q.order_by,
            limit=q.limit,
            time_constraint_start=q.start_time,
            time_constraint_end=q.end_time,
        )
        
        result = self.engine.query(request)
        return self._to_dataframe(result.result_df)
    
    def explain(self, q: Query) -> str:
        """Get the SQL that MetricFlow would generate."""
        request = MetricFlowQueryRequest.create_with_random_request_id(
            metric_names=q.metrics,
            group_by_names=q.group_by,
            where_constraints=q.where,
            order_by_names=q.order_by,
            limit=q.limit,
            time_constraint_start=q.start_time,
            time_constraint_end=q.end_time,
        )
        
        result = self.engine.explain(request)
        return result.sql_statement.sql
    
    @staticmethod
    def _to_dataframe(mf_table: MetricFlowDataTable) -> pd.DataFrame:
        """Convert MetricFlowDataTable to pandas DataFrame."""
        data = {}
        for i, col_name in enumerate(mf_table.column_names):
            data[col_name] = list(mf_table.column_values_iterator(i))
        return pd.DataFrame(data)


# =============================================================================
# Example Usage
# =============================================================================

def test_examples():
    print("=" * 60)
    print("MetricFlow Python API")
    print("=" * 60)
    
    # Determine project directory (app/ is inside the repo root)
    repo_root = Path(__file__).parent.parent
    project_dir = repo_root / "mf_tutorial_project"
    
    if not project_dir.exists():
        print(f"Error: Can't find dbt project at {project_dir}")
        sys.exit(1)
    
    print(f"Project: {project_dir}\n")
    
    try:
        mf = MetricFlow(project_dir=project_dir, profiles_dir=project_dir)
        print("✓ MetricFlow initialized!\n")
    except Exception as e:
        print(f"✗ Failed: {e}")
        sys.exit(1)
    
    print(f"Metrics: {mf.list_metrics()}\n")
    
    # =========================================================================
    # Test queries from README.md
    # =========================================================================
    
    print("=" * 60)
    print("Test 1: Add dimension")
    print("=" * 60)
    q = Query(
        metrics=["transactions"],
        group_by=["metric_time", "customer__customer_country"],
        order_by=["metric_time"],
        limit=10,
    )
    print(mf.query(q))
    
    print("\n" + "=" * 60)
    print("Test 2: Change granularity")
    print("=" * 60)
    q = Query(
        metrics=["transactions"],
        group_by=["metric_time__week"],
        order_by=["metric_time__week"],
    )
    print(mf.query(q))
    
    print("\n" + "=" * 60)
    print("Test 3: Multi-metric with time filter")
    print("=" * 60)
    q = Query(
        metrics=["transactions", "transaction_amount"],
        group_by=["metric_time", "transaction__is_large"],
        order_by=["metric_time"],
        start_time=datetime.datetime(2022, 3, 20),
        end_time=datetime.datetime(2022, 4, 1),
    )
    print(mf.query(q))
    
    print("\n" + "=" * 60)
    print("Test 4: Multi-metric with where filter")
    print("=" * 60)
    q = Query(
        metrics=["transactions", "spend"],
        group_by=["metric_time__month", "country"],
        order_by=["metric_time"],
        start_time=datetime.datetime(2022, 3, 20),
        end_time=datetime.datetime(2022, 4, 1),
        where=["{{ Entity('country') }} <> 'GR'"],
    )
    print(mf.query(q))
    
    print("\n" + "=" * 60)
    print("Test 5: Explain (get SQL)")
    print("=" * 60)
    q = Query(
        metrics=["transactions"],
        group_by=["metric_time__week"],
    )
    print(mf.explain(q))
    
    print("\n✓ Done!")


if __name__ == "__main__":
    test_examples()