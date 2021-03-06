# -*- coding: utf-8 -*-
# Copyright 2019 Matrix.org Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from mock import Mock

from twisted.internet import defer

from synapse.api.errors import Codes, SynapseError
from synapse.rest import admin
from synapse.rest.client.v1 import login, room
from synapse.types import UserID

from tests import unittest


class RoomComplexityTests(unittest.FederatingHomeserverTestCase):

    servlets = [
        admin.register_servlets,
        room.register_servlets,
        login.register_servlets,
    ]

    def default_config(self):
        config = super().default_config()
        config["limit_remote_rooms"] = {"enabled": True, "complexity": 0.05}
        return config

    def test_complexity_simple(self):

        u1 = self.register_user("u1", "pass")
        u1_token = self.login("u1", "pass")

        room_1 = self.helper.create_room_as(u1, tok=u1_token)
        self.helper.send_state(
            room_1, event_type="m.room.topic", body={"topic": "foo"}, tok=u1_token
        )

        # Get the room complexity
        request, channel = self.make_request(
            "GET", "/_matrix/federation/unstable/rooms/%s/complexity" % (room_1,)
        )
        self.render(request)
        self.assertEquals(200, channel.code)
        complexity = channel.json_body["v1"]
        self.assertTrue(complexity > 0, complexity)

        # Artificially raise the complexity
        store = self.hs.get_datastore()
        store.get_current_state_event_counts = lambda x: defer.succeed(500 * 1.23)

        # Get the room complexity again -- make sure it's our artificial value
        request, channel = self.make_request(
            "GET", "/_matrix/federation/unstable/rooms/%s/complexity" % (room_1,)
        )
        self.render(request)
        self.assertEquals(200, channel.code)
        complexity = channel.json_body["v1"]
        self.assertEqual(complexity, 1.23)

    def test_join_too_large(self):

        u1 = self.register_user("u1", "pass")

        handler = self.hs.get_room_member_handler()
        fed_transport = self.hs.get_federation_transport_client()

        # Mock out some things, because we don't want to test the whole join
        fed_transport.client.get_json = Mock(return_value=defer.succeed({"v1": 9999}))
        handler.federation_handler.do_invite_join = Mock(
            return_value=defer.succeed(("", 1))
        )

        d = handler._remote_join(
            None,
            ["other.example.com"],
            "roomid",
            UserID.from_string(u1),
            {"membership": "join"},
        )

        self.pump()

        # The request failed with a SynapseError saying the resource limit was
        # exceeded.
        f = self.get_failure(d, SynapseError)
        self.assertEqual(f.value.code, 400, f.value)
        self.assertEqual(f.value.errcode, Codes.RESOURCE_LIMIT_EXCEEDED)

    def test_join_too_large_once_joined(self):

        u1 = self.register_user("u1", "pass")
        u1_token = self.login("u1", "pass")

        # Ok, this might seem a bit weird -- I want to test that we actually
        # leave the room, but I don't want to simulate two servers. So, we make
        # a local room, which we say we're joining remotely, even if there's no
        # remote, because we mock that out. Then, we'll leave the (actually
        # local) room, which will be propagated over federation in a real
        # scenario.
        room_1 = self.helper.create_room_as(u1, tok=u1_token)

        handler = self.hs.get_room_member_handler()
        fed_transport = self.hs.get_federation_transport_client()

        # Mock out some things, because we don't want to test the whole join
        fed_transport.client.get_json = Mock(return_value=defer.succeed(None))
        handler.federation_handler.do_invite_join = Mock(
            return_value=defer.succeed(("", 1))
        )

        # Artificially raise the complexity
        self.hs.get_datastore().get_current_state_event_counts = lambda x: defer.succeed(
            600
        )

        d = handler._remote_join(
            None,
            ["other.example.com"],
            room_1,
            UserID.from_string(u1),
            {"membership": "join"},
        )

        self.pump()

        # The request failed with a SynapseError saying the resource limit was
        # exceeded.
        f = self.get_failure(d, SynapseError)
        self.assertEqual(f.value.code, 400)
        self.assertEqual(f.value.errcode, Codes.RESOURCE_LIMIT_EXCEEDED)
