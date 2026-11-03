from pipeline.ir import binary, call, lit, ref
from pipeline.schemas import (
    ArrayExpression,
    AuxiliaryVariable,
    ConstantVariable,
    Dimension,
    FlowEndpoint,
    FlowVariable,
    IndexedExpression,
    ModelDocument,
    StockVariable,
    TimeSettings,
)
from pipeline.validation import finalize_model


def array_model() -> ModelDocument:
    return finalize_model(
        ModelDocument(
            description="Subscripted populations",
            time=TimeSettings(unit="year", final_time=1, time_step=0.25, saveper=0.25),
            dimensions=[Dimension(id="region", elements=["North", "South"])],
            variables=[
                StockVariable(
                    id="population",
                    kind="stock",
                    subscripts=["region"],
                    initial=ArrayExpression(op="array", values=[lit(100), lit(200)]),
                    units={"person": 1},
                ),
                FlowVariable(
                    id="births",
                    kind="flow",
                    subscripts=["region"],
                    expression=binary("mul", ref("population"), ref("rate")),
                    source=FlowEndpoint(kind="cloud", id="births_source"),
                    target=FlowEndpoint(kind="stock", id="population"),
                    units={"person": 1, "year": -1},
                ),
                ConstantVariable(
                    id="rate",
                    kind="constant",
                    subscripts=["region"],
                    expression=ArrayExpression(op="array", values=[lit(0.1), lit(0.2)]),
                    units={"year": -1},
                ),
                AuxiliaryVariable(
                    id="total_population",
                    kind="auxiliary",
                    expression=call("sum", ref("population")),
                    units={"person": 1},
                ),
                AuxiliaryVariable(
                    id="north_population",
                    kind="auxiliary",
                    expression=IndexedExpression(
                        op="index", name="population", indices={"region": "North"}
                    ),
                    units={"person": 1},
                ),
            ],
        )
    )
