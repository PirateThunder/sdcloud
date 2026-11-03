from pipeline.ir import binary, lit, ref
from pipeline.schemas import (
    ConstantVariable,
    FlowEndpoint,
    FlowVariable,
    ModelDocument,
    StockVariable,
    TimeSettings,
)
from pipeline.validation import finalize_model


def exponential_model() -> ModelDocument:
    return make_model(
        [
            StockVariable(
                id="population",
                kind="stock",
                initial=lit(100),
                units={"person": 1},
            ),
            FlowVariable(
                id="growth",
                kind="flow",
                expression=binary("mul", ref("population"), ref("growth_rate")),
                source=FlowEndpoint(kind="cloud", id="growth_source"),
                target=FlowEndpoint(kind="stock", id="population"),
                units={"person": 1, "year": -1},
            ),
            ConstantVariable(
                id="growth_rate",
                kind="constant",
                expression=lit(0.1),
                units={"year": -1},
            ),
        ]
    )


def sir_model() -> ModelDocument:
    return make_model(
        [
            StockVariable(
                id="susceptible", kind="stock", initial=ref("total_population"), units={"person": 1}
            ),
            StockVariable(id="infectious", kind="stock", initial=lit(5), units={"person": 1}),
            StockVariable(id="recovered", kind="stock", initial=lit(0), units={"person": 1}),
            FlowVariable(
                id="succumbing",
                kind="flow",
                expression=binary(
                    "mul",
                    binary(
                        "div",
                        binary("mul", ref("susceptible"), ref("infectious")),
                        ref("total_population"),
                    ),
                    ref("contact_infectivity"),
                ),
                source=FlowEndpoint(kind="stock", id="susceptible"),
                target=FlowEndpoint(kind="stock", id="infectious"),
                units={"person": 1, "day": -1},
            ),
            FlowVariable(
                id="recovering",
                kind="flow",
                expression=binary("div", ref("infectious"), ref("duration")),
                source=FlowEndpoint(kind="stock", id="infectious"),
                target=FlowEndpoint(kind="stock", id="recovered"),
                units={"person": 1, "day": -1},
            ),
            ConstantVariable(
                id="total_population", kind="constant", expression=lit(1000), units={"person": 1}
            ),
            ConstantVariable(
                id="contact_infectivity", kind="constant", expression=lit(0.3), units={"day": -1}
            ),
            ConstantVariable(id="duration", kind="constant", expression=lit(5), units={"day": 1}),
        ],
        time_unit="day",
        final_time=10,
        time_step=0.125,
    )


def make_model(
    variables: list,
    *,
    time_unit: str = "year",
    final_time: float = 10,
    time_step: float = 0.25,
) -> ModelDocument:
    document = ModelDocument(
        description="Scientific test model",
        time=TimeSettings(
            unit=time_unit,
            final_time=final_time,
            time_step=time_step,
            saveper=time_step,
        ),
        variables=variables,
    )
    return finalize_model(document)
