"""Automatic startup and stale-ACK boundaries without serial/Dolphin access."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.wiimote_bridge import __main__ as cli
from tools.wiimote_bridge.mailbox import MailboxBusyError
from tools.wiimote_bridge.mapping import DeviceRegistry
from tools.wiimote_bridge.service import HostView, neutral_slot


class AssignmentCliTests(unittest.TestCase):
    def test_default_start_needs_no_mac_config_and_ignores_old_reservations(self):
        args = cli.argument_parser().parse_args(["--diagnose"])
        with patch.object(DeviceRegistry, "load", side_effect=AssertionError("must not load MAC config")):
            self.assertEqual(cli._registry(args).assignments, {})

    def test_manual_mode_retains_explicit_old_config(self):
        args = cli.argument_parser().parse_args(["--manual-mapping", "--config", "old.json"])
        saved = DeviceRegistry({"00:11:22:33:44:55": 8})
        with patch.object(DeviceRegistry, "load", return_value=saved) as load:
            self.assertIs(cli._registry(args), saved)
            load.assert_called_once_with(Path("old.json"))

    def test_cli_constructs_automatic_service_by_default_and_manual_only_on_request(self):
        for extra, automatic in (([], True), (["--manual-mapping"], False)):
            captured = []
            with patch.object(cli, "_registry", return_value=DeviceRegistry()), \
                    patch.object(cli, "_serial", side_effect=lambda args, service, parser: captured.append(service)):
                self.assertEqual(cli.main(["--diagnose", *extra]), 0)
            self.assertEqual(captured[0].automatic_assignment, automatic)

    def make_stream(self):
        view = HostView(42, tuple(neutral_slot(i) for i in range(4)), (), (), ())
        acknowledgements = []
        service = SimpleNamespace(boot_session=42, routing_revision=1,
                                  view=lambda **kwargs: view,
                                  acknowledge_guest=acknowledgements.append)
        published = []
        mailbox = SimpleNamespace(host_session=33)
        mailbox.renew_host_session = lambda: setattr(mailbox, "host_session", 44)
        mailbox.publish = lambda view, **kwargs: published.append((mailbox.host_session, view))
        return service, mailbox, published, acknowledgements

    def test_replacement_rejects_old_session_ack_even_with_matching_event_number(self):
        service, mailbox, published, acknowledgements = self.make_stream()
        mailbox.read_status = lambda: SimpleNamespace(host_session=33, source_session=42,
                                                      flags=3, acknowledged_events=(1, 0, 0, 0))
        revision = cli._publish_view(service, mailbox, now_ms=1, elapsed_ms=1, routing_revision=0)
        self.assertEqual(revision, 1)
        self.assertEqual(published[0][0], 44)
        self.assertEqual(acknowledgements, [])
        mailbox.read_status = lambda: SimpleNamespace(host_session=44, source_session=42,
                                                      flags=3, acknowledged_events=(1, 0, 0, 0))
        cli._publish_view(service, mailbox, now_ms=2, elapsed_ms=2, routing_revision=revision)
        self.assertEqual(acknowledgements, [(1, 0, 0, 0)])

    def test_unchanged_binding_keeps_session_and_busy_status_never_acknowledges(self):
        service, mailbox, published, acknowledgements = self.make_stream()
        mailbox.read_status = lambda: (_ for _ in ()).throw(MailboxBusyError("busy"))
        cli._publish_view(service, mailbox, now_ms=1, elapsed_ms=1, routing_revision=1)
        self.assertEqual(published[0][0], 33)
        self.assertEqual(acknowledgements, [])


if __name__ == "__main__":
    unittest.main()
