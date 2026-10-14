"""下载票据：浏览器原生下载带不了自定义头，所以用一张短命票据换令牌。"""

import time
import unittest

from app.api.tickets import MAX_TICKETS, DownloadTickets


class TicketTests(unittest.TestCase):
    def setUp(self):
        self.tickets = DownloadTickets()

    def test_verify_accepts_its_own_binding(self):
        ticket = self.tickets.issue("vm1", "/home/a/x.txt")
        self.assertTrue(self.tickets.verify(ticket, "vm1", "/home/a/x.txt"))

    def test_verify_rejects_other_connection(self):
        ticket = self.tickets.issue("vm1", "/home/a/x.txt")
        self.assertFalse(self.tickets.verify(ticket, "vm2", "/home/a/x.txt"))

    def test_verify_rejects_other_path(self):
        # 票据只换一个文件，不能顺手换到别的路径上。
        ticket = self.tickets.issue("vm1", "/home/a/x.txt")
        self.assertFalse(self.tickets.verify(ticket, "vm1", "/etc/shadow"))

    def test_verify_rejects_empty_and_unknown(self):
        self.assertFalse(self.tickets.verify(None, "vm1", "/x"))
        self.assertFalse(self.tickets.verify("", "vm1", "/x"))
        self.assertFalse(self.tickets.verify("not-a-ticket", "vm1", "/x"))

    def test_peek_ignores_binding(self):
        # 路由层用它决定是否跳过令牌校验 —— 那时还不知道 URL 里的连接与路径。
        ticket = self.tickets.issue("vm1", "/x")
        self.assertTrue(self.tickets.peek(ticket))
        self.assertFalse(self.tickets.peek("nope"))
        self.assertFalse(self.tickets.peek(None))

    def test_tokens_are_random_and_unique(self):
        issued = {self.tickets.issue("vm1", "/x") for _ in range(50)}
        self.assertEqual(len(issued), 50)
        self.assertTrue(all(len(t) >= 20 for t in issued))

    def test_expiry(self):
        self.tickets = DownloadTickets(ttl=0.05)
        ticket = self.tickets.issue("vm1", "/x")
        self.assertTrue(self.tickets.verify(ticket, "vm1", "/x"))
        time.sleep(0.12)
        self.assertFalse(self.tickets.verify(ticket, "vm1", "/x"))
        self.assertFalse(self.tickets.peek(ticket))
        self.assertEqual(self.tickets.count, 0)

    def test_reusable_within_ttl(self):
        # 刻意不做一次性：用户在「另存为」里点取消、或浏览器重试一次时，
        # 一次性票据已经失效，用户会看到一个莫名其妙的错误。
        ticket = self.tickets.issue("vm1", "/x")
        self.assertTrue(self.tickets.verify(ticket, "vm1", "/x"))
        self.assertTrue(self.tickets.verify(ticket, "vm1", "/x"))

    def test_clear(self):
        self.tickets.issue("vm1", "/x")
        self.tickets.clear()
        self.assertEqual(self.tickets.count, 0)

    def test_capacity_is_bounded(self):
        # assertLogs 同时把「已回收最早的一张」的 warning 收进断言里，不刷屏。
        with self.assertLogs("app.api.tickets", level="WARNING"):
            for index in range(MAX_TICKETS + 20):
                self.tickets.issue("vm1", f"/x{index}")
        self.assertLessEqual(self.tickets.count, MAX_TICKETS)

    def test_oldest_is_evicted_first(self):
        first = self.tickets.issue("vm1", "/first")
        with self.assertLogs("app.api.tickets", level="WARNING"):
            for index in range(MAX_TICKETS):
                self.tickets.issue("vm1", f"/x{index}")
        self.assertFalse(self.tickets.peek(first))


if __name__ == "__main__":
    unittest.main()
