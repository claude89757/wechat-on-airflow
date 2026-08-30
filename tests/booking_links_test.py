import unittest
from datetime import datetime, timedelta

from wechat_airflow.notifications import booking_links


class BookingLinksTest(unittest.TestCase):
    def test_szw_and_gba_share_the_weilaihui_program(self):
        szw = booking_links.program_for_venue("szw")
        gba = booking_links.program_for_venue("gba")
        self.assertIsNotNone(szw)
        self.assertEqual(szw, gba)
        self.assertEqual(szw.program_id, "weilaihui")
        self.assertEqual(szw.link, "#小程序://未来荟/XL8wsbG5boBuZSl")

    def test_unknown_venues_have_no_booking_link(self):
        self.assertIsNone(booking_links.program_for_venue(None))
        self.assertIsNone(booking_links.program_for_venue(" "))
        self.assertIsNone(booking_links.program_for_venue("unknown"))

    def test_active_venues_have_registered_booking_links(self):
        catalog = {
            "szw": booking_links.WEILAIHUI,
            "gba": booking_links.WEILAIHUI,
            "dsh_free": booking_links.DSH_FREE_PROGRAM,
            "dsh": booking_links.DSH_PROGRAM,
            "sysh": booking_links.SYSH_PROGRAM,
            "tops": booking_links.TOPS_PROGRAM,
            "fsb": booking_links.FSB_PROGRAM,
            "fsb_shenyun": booking_links.FSB_PROGRAM,
            "fsb_shekou": booking_links.FSB_PROGRAM,
            "fsb_xinan": booking_links.FSB_PROGRAM,
            "fsb_zhengzhong": booking_links.FSB_PROGRAM,
            "fsb_atuoshan": booking_links.FSB_PROGRAM,
            "fsb_zonglvquan": booking_links.FSB_PROGRAM,
            "fsb_guanhu": booking_links.FSB_PROGRAM,
            "fsb_bantian": booking_links.FSB_PROGRAM,
            "fsb_shahe": booking_links.FSB_PROGRAM,
            "fsb_baoshui": booking_links.FSB_PROGRAM,
            "fsb_nanyou": booking_links.FSB_PROGRAM,
            "fsb_xinqiao": booking_links.FSB_PROGRAM,
            "fsb_yifangcheng": booking_links.FSB_PROGRAM,
            "fsb_qilin": booking_links.FSB_PROGRAM,
            "fsb_maozhouhe": booking_links.FSB_PROGRAM,
            "ppba": booking_links.PPBA_PROGRAM,
            "tyzx": booking_links.TYZX_PROGRAM,
            "jdwx": booking_links.JDWX_PROGRAM,
        }
        self.assertEqual(set(catalog), set(booking_links.VENUE_BOOKING_PROGRAMS))
        for venue_id, program in catalog.items():
            self.assertEqual(booking_links.program_for_venue(venue_id), program)

    def test_attach_footer_adds_the_scheme_once_as_the_last_line(self):
        message = "【深圳湾1号场】星期二(08-18)空场: 18:00-19:00"
        attached = booking_links.attach_footer(message, booking_links.WEILAIHUI.link)
        self.assertEqual(
            attached,
            "【深圳湾1号场】星期二(08-18)空场: 18:00-19:00\n\n#小程序://未来荟/XL8wsbG5boBuZSl",
        )
        self.assertEqual(
            booking_links.attach_footer(attached, booking_links.WEILAIHUI.link), attached
        )

    def test_plan_attaches_once_then_cools_down_for_the_same_program(self):
        now = datetime(2026, 8, 18, 18, 5)
        first = booking_links.plan_booking_link(
            "slot-a",
            receiver="Zacks_A",
            venue_id="szw",
            cache={},
            now=now,
        )
        self.assertIn("#小程序://未来荟/XL8wsbG5boBuZSl", first.message)
        self.assertIsNotNone(first.cache)

        second = booking_links.plan_booking_link(
            "slot-b",
            receiver="Zacks_A",
            venue_id="gba",
            cache=first.cache,
            now=now + timedelta(hours=1),
        )
        self.assertEqual(second.message, "slot-b")
        self.assertIsNone(second.cache)

        later = booking_links.plan_booking_link(
            "slot-c",
            receiver="Zacks_A",
            venue_id="szw",
            cache=first.cache,
            now=now + timedelta(hours=2),
        )
        self.assertIn("#小程序://未来荟/XL8wsbG5boBuZSl", later.message)

    def test_plan_is_independent_per_chat_and_per_program(self):
        now = datetime(2026, 8, 18, 18, 5)
        zacks_a = booking_links.plan_booking_link(
            "szw-a",
            receiver="Zacks_A",
            venue_id="szw",
            cache={},
            now=now,
        )
        zacks_b = booking_links.plan_booking_link(
            "szw-b",
            receiver="Zacks_B",
            venue_id="szw",
            cache=zacks_a.cache,
            now=now,
        )
        tops = booking_links.plan_booking_link(
            "tops",
            receiver="Zacks_A",
            venue_id="tops",
            cache=zacks_b.cache,
            now=now,
        )
        self.assertIn("#小程序://未来荟/XL8wsbG5boBuZSl", zacks_b.message)
        self.assertIn("#小程序://Tops网球/lo2x6SO0XGpdUph", tops.message)
        self.assertEqual(booking_links.JDWX_PROGRAM.link, "#小程序://ing在运动/8EnsqtWMGoMe6Kr")
        self.assertEqual(
            booking_links.DSH_FREE_PROGRAM.link, "#小程序://南山文体通/C28W6ASVGvL4usz"
        )
        self.assertEqual(booking_links.TYZX_PROGRAM.link, "#小程序://i深体/GA0nZbyQSAq9iSa")
        self.assertEqual(
            booking_links.program_for_venue("dsh_free"), booking_links.DSH_FREE_PROGRAM
        )
        self.assertEqual(booking_links.program_for_venue("dsh"), booking_links.DSH_PROGRAM)
        self.assertEqual(booking_links.DSH_PROGRAM.link, "#小程序://威逊文体/il2QpVgwVeghPtg")
        self.assertEqual(booking_links.program_for_venue("fsb"), booking_links.FSB_PROGRAM)
        self.assertEqual(booking_links.FSB_PROGRAM.link, "#小程序://泛思博特/D0aY3jOJ2oq34fh")
        self.assertEqual(booking_links.program_for_venue("ppba"), booking_links.PPBA_PROGRAM)
        self.assertEqual(
            booking_links.PPBA_PROGRAM.link,
            "#小程序://PICKLEPOP宝安摩天轮馆/PK3I72u2dNFoA2b",
        )
        self.assertEqual(booking_links.program_for_venue("tyzx"), booking_links.TYZX_PROGRAM)
        self.assertEqual(
            booking_links.SYSH_PROGRAM.link,
            "#小程序://上越网球中心-沙河店/mug6ErSFWCSdvvc",
        )

    def test_restore_sent_clears_a_failed_claim(self):
        now = datetime(2026, 8, 18, 18, 5)
        claimed = booking_links.mark_sent({}, "Zacks_A", "weilaihui", now)
        restored = booking_links.restore_sent(claimed, "Zacks_A", "weilaihui", None)
        self.assertEqual(restored, {})


if __name__ == "__main__":
    unittest.main()
