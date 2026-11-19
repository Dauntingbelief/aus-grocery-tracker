import pytest

from grocery_tracker.units import PackSize, parse_pack_size, unit_price


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("500g", PackSize(0.5, "kg")),
        ("1.2kg", PackSize(1.2, "kg")),
        ("2L", PackSize(2.0, "L")),
        ("300mL", PackSize(0.3, "L")),
        ("12ea", PackSize(12.0, "each")),
        ("1 each", PackSize(1.0, "each")),
        ("5x72g", PackSize(0.36, "kg")),  # Decimal maths: exactly 0.36, no float noise
        ("24 x 600mL", PackSize(14.4, "L")),
        ("6×375ML", PackSize(2.25, "L")),  # unicode multiply sign, upper-case unit
        ("  750ml ", PackSize(0.75, "L")),
    ],
)
def test_parse_pack_size(text, expected):
    assert parse_pack_size(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "500", "g500", "2 litres", "0g", "-1kg"])
def test_parse_pack_size_rejects_bad_input(text):
    with pytest.raises(ValueError):
        parse_pack_size(text)


def test_unit_price_per_kg():
    # $6.50 for 500g = $13.00/kg
    assert unit_price(6.50, parse_pack_size("500g")) == 13.0


def test_unit_price_multipack_per_litre():
    # $7.20 for 24 x 600mL (14.4 L) = $0.50/L
    assert unit_price(7.20, parse_pack_size("24x600mL")) == 0.5


def test_unit_price_rounds_to_4dp():
    assert unit_price(1.00, parse_pack_size("3ea")) == 0.3333
