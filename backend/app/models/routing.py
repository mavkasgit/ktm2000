import enum


class RouteOperationFamily(str, enum.Enum):
    NONE = "NONE"
    DRILL = "DRILL"
    PRESS = "PRESS"
    PACK = "PACK"


class RouteOutputKind(str, enum.Enum):
    finished_good = "finished_good"
    semi_finished_shipment = "semi_finished_shipment"
