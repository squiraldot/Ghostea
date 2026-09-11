import unittest

from ghostea.services.group_authorization import GroupAuthorizationService


class FakeMember:
    def __init__(self, status, user_id=1):
        self.status = status
        self.user = type('U', (), {'id': user_id})()


class GroupAuthorizationUnitTests(unittest.TestCase):
    def test_admin_statuses(self):
        self.assertTrue(GroupAuthorizationService._is_admin(FakeMember('administrator')))
        self.assertTrue(GroupAuthorizationService._is_admin(FakeMember('creator')))
        self.assertFalse(GroupAuthorizationService._is_admin(FakeMember('member')))
        self.assertFalse(GroupAuthorizationService._is_admin(FakeMember('left')))


if __name__ == '__main__':
    unittest.main()
