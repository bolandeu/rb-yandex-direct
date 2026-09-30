"""The provider contract: every provider implements health_check(), discovery finds them."""

from __future__ import annotations

import gc

import pytest

from rb_yandex_direct.providers import Health, Provider, all_providers

# --- provider contract: every provider can prove its credential works -------------


@pytest.mark.parametrize("provider_cls", all_providers(), ids=lambda cls: cls.name)
def test_every_provider_implements_health_check(provider_cls: type[Provider]) -> None:
    # Only the override is checked: constructing a provider may need config or
    # env, which is `for_health_check()`'s job, not this test's.
    assert provider_cls.health_check is not Provider.health_check, (
        f"{provider_cls.__name__} must implement health_check() — `auth status --check` calls it"
    )


def test_provider_names_are_unique() -> None:
    names = [cls.name for cls in all_providers()]
    assert len(names) == len(set(names)), f"duplicate provider names: {names}"


def test_all_providers_discovers_package_classes_only() -> None:
    # Subclasses stay registered on Provider while they're referenced, so this
    # test drops them (and collects) at the end — later tests see the real set.
    def make_classes() -> tuple[type, type, type]:
        class Found(Provider):
            __module__ = "rb_yandex_direct.providers.fake"
            name = "found"

            def health_check(self) -> Health:
                return Health()

        class Base(Provider):
            __module__ = "rb_yandex_direct.providers.fake"
            abstract = True

        class Elsewhere(Provider):  # defined outside providers/: not discovered
            name = "elsewhere"

        return Found, Base, Elsewhere

    before = set(all_providers())
    found, base, elsewhere = make_classes()
    discovered = all_providers()
    assert found in discovered
    assert base not in discovered
    assert elsewhere not in discovered
    del found, base, elsewhere, discovered
    gc.collect()
    assert set(all_providers()) == before
