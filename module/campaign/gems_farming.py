from datetime import datetime

import inflection

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import get_color
from module.campaign.campaign_base import CampaignBase
from module.campaign.run import CampaignRun
from module.combat.assets import BATTLE_PREPARATION
from module.combat.emotion import Emotion, FleetEmotion
from module.config.utils import get_server_next_update
from module.equipment.assets import *
from module.equipment.fleet_equipment import FleetEquipment
from module.exception import CampaignEnd, ScriptError, RequestHumanTakeover
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF
from module.logger import logger
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION
from module.retire.assets import (
    DOCK_CHECK,
    TEMPLATE_BOGUE, TEMPLATE_HERMES, TEMPLATE_LANGLEY, TEMPLATE_RANGER,
    TEMPLATE_CASSIN_1, TEMPLATE_CASSIN_2, TEMPLATE_DOWNES_1, TEMPLATE_DOWNES_2,
    TEMPLATE_AULICK, TEMPLATE_FOOTE
)

from module.retire.dock import Dock, CARD_GRIDS
from module.retire.scanner import ShipScanner
from module.ui.assets import BACK_ARROW
from module.ui.page import page_fleet

SIM_VALUE = 0.92
EMOTION_LIMIT = 4

HARD_FLEET_GRIDS = ButtonGrid(
    origin=(417, 207), delta=(105, 115), button_shape=(30, 30), grid_shape=(6, 2), name='HARD_FLEET')


class GemsFleetEmotion(FleetEmotion):

    @property
    def limit(self):
        return EMOTION_LIMIT

    def update(self):
        self.current = self.value
        if self.current < 119:
            super().update()


class GemsEmotion(Emotion):

    def __init__(self, config):
        self.config = config
        self.fleet_1 = GemsFleetEmotion(self.config, fleet=1)
        self.fleet_2 = GemsFleetEmotion(self.config, fleet=2)
        self.fleets = [self.fleet_1, self.fleet_2]

    def check_reduce(self, battle):
        if not self.is_calculate:
            return

        if self.config.Fleet_FleetOrder == 'fleet1_standby_fleet2_all':
            battle = (0, battle * self.reduce_per_battle_before_entering)
        else:
            battle = (battle * self.reduce_per_battle_before_entering, 0)

        logger.info(f'Expect emotion reduce: {battle}')
        self.update()
        self.record()
        self.show()
        recovered = max([f.get_recovered(b) for f, b in zip(self.fleets, battle)])
        if recovered > datetime.now():
            logger.hr('EMOTION CONTROL')
            raise CampaignEnd('Emotion control')

    def wait(self, fleet_index):
        pass


class GemsCampaignOverride(CampaignBase):

    hard_not_satisfied = CampaignEnd('Hard not satisfied')

    def handle_combat_low_emotion(self):
        """
        Overwrite info_handler.handle_combat_low_emotion()
        If change vanguard is enabled, withdraw combat and change flagship and vanguard
        """
        if self.config.GemsFarming_ChangeVanguard == 'disabled':
            result = self.handle_popup_confirm('IGNORE_LOW_EMOTION')
            if result:
                # Avoid clicking AUTO_SEARCH_MAP_OPTION_OFF
                self.interval_reset(AUTO_SEARCH_MAP_OPTION_OFF)
            return result

        if self.handle_popup_cancel('IGNORE_LOW_EMOTION'):
            self.config.GEMS_EMOTION_TRIGGRED = True
            logger.hr('EMOTION WITHDRAW')

            while 1:
                self.device.screenshot()

                if self.handle_story_skip():
                    continue
                if self.handle_popup_cancel('IGNORE_LOW_EMOTION'):
                    continue

                if self.appear(BATTLE_PREPARATION, offset=(20, 20), interval=2):
                    self.device.click(BACK_ARROW)
                    continue
                if self.handle_auto_search_exit():
                    continue
                if self.is_in_stage():
                    break

                if self.is_in_map():
                    self.withdraw()
                    break

                if self.appear(FLEET_PREPARATION, offset=(20, 50), interval=2) \
                        or self.appear(MAP_PREPARATION, offset=(20, 20), interval=2):
                    self.enter_map_cancel()
                    break
            raise CampaignEnd('Emotion withdraw')

    @cached_property
    def emotion(self) -> GemsEmotion:
        return GemsEmotion(config=self.config)


class GemsFarming(CampaignRun, FleetEquipment, Dock):

    def load_campaign(self, name, folder='campaign_main'):
        super().load_campaign(name, folder)

        class GemsCampaign(GemsCampaignOverride, self.module.Campaign):
            pass

        self.campaign: GemsCampaign = GemsCampaign(device=self.campaign.device, config=self.campaign.config)
        self.campaign.config.override(EnemyPriority_EnemyScaleBalanceWeight='S1_enemy_first')

    @property
    def change_flagship(self):
        return 'ship' in self.config.GemsFarming_ChangeFlagship

    @property
    def change_flagship_equip(self):
        return 'equip' in self.config.GemsFarming_ChangeFlagship

    @property
    def change_vanguard(self):
        return 'ship' in self.config.GemsFarming_ChangeVanguard

    @property
    def change_vanguard_equip(self):
        return 'equip' in self.config.GemsFarming_ChangeVanguard

    @property
    def is_hard_mode(self):
        return inflection.underscore(self.config.Campaign_Name) in [
            'c1', 'c2', 'c3',
            'd1', 'd2', 'd3',
            'ht1', 'ht2', 'ht3', 'ht4', 'ht5', 'ht6',
        ]

    @property
    def fleet_to_attack(self):
        if self.config.Fleet_FleetOrder == 'fleet1_standby_fleet2_all':
            return self.config.Fleet_Fleet2
        else:
            return self.config.Fleet_Fleet1

    def set_emotion(self, emotion):
        if hasattr(self, 'campaign'):
            config = self.campaign.config
        else:
            config = self.config
        if config.Fleet_FleetOrder == 'fleet1_standby_fleet2_all':
            config.set_record(Emotion_Fleet2Value=emotion)
        else:
            config.set_record(Emotion_Fleet1Value=emotion)

    def goto_fleet_hard(self):
        if self.appear(FLEET_PREPARATION, offset=(20, 50)):
            return
        if self.campaign.is_in_auto_search_menu():
            logger.info('In auto search menu, closing.')
            self.campaign.ensure_auto_search_exit()
            self.campaign.ensure_campaign_ui(name=self.stage)
        else:
            self.campaign.ensure_campaign_ui(name=self.stage)
        self.campaign.ENTRANCE.area = self.campaign.ENTRANCE.button

        button = self.campaign.ENTRANCE
        campaign_click = 0
        campaign_timer = Timer(5)
        map_timer = Timer(5)
        skip_first_screenshot = True
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # Check errors
            if campaign_click > 5:
                logger.critical(f"Failed to enter {button}, too many click on {button}")
                logger.critical("Possible reason #1: You haven't reached the commander level to unlock this stage.")
                raise RequestHumanTakeover

            # Map preparation
            if map_timer.reached() and self.campaign.handle_map_preparation():
                self.device.click(MAP_PREPARATION)
                map_timer.reset()
                campaign_timer.reset()
                continue

            # Fleet preparation
            if campaign_click and self.appear(FLEET_PREPARATION, offset=(20, 50)):
                break

            # Enter campaign
            if campaign_timer.reached() and self.appear_then_click(button):
                campaign_click += 1
                campaign_timer.reset()
                continue

            # Retire
            if self.campaign.handle_retirement():
                continue

            # Emotion
            if self.campaign.handle_combat_low_emotion():
                continue

    @cached_property
    def hard_grid_y(self):
        if self.config.Fleet_FleetOrder == 'fleet1_standby_fleet2_all':
            return 1
        else:
            return 0

    def is_ship_in_use(self, x):
        r, g, b = get_color(self.device.image, HARD_FLEET_GRIDS[(x, self.hard_grid_y)].area)
        return 0.299 * r + 0.587 * g + 0.114 * b > 100

    def flagship_change_hard(self):
        self.goto_fleet_hard()
        if self.is_ship_in_use(0):
            self.ui_click(HARD_FLEET_GRIDS[(0, self.hard_grid_y)],
                          appear_button=FLEET_PREPARATION, check_button=DOCK_CHECK, skip_first_screenshot=True)
            self.ui_click(CARD_GRIDS[(0, 0)],
                          appear_button=DOCK_CHECK, check_button=FLEET_PREPARATION, skip_first_screenshot=True)
        self.ui_click(HARD_FLEET_GRIDS[(self.config.GemsFarming_HardFlagshipIndex, self.hard_grid_y)],
                      appear_button=FLEET_PREPARATION, check_button=DOCK_CHECK, skip_first_screenshot=True)
        self.dock_filter_set(
            index='cv', rarity='common', extra='enhanceable', sort='total')
        self.dock_favourite_set(False)

        ships = self.get_common_rarity_cv()
        if ships:
            ship = min(ships, key=lambda s: (s.level, -s.emotion))
            self._new_emotion_value = min(ship.emotion, self._new_emotion_value)
            self.dock_select_one(ship.button)
            self._dock_reset()
            self.dock_select_confirm(check_button=FLEET_PREPARATION)

            logger.info('Change flagship success')
            return True
        else:
            logger.info('Change flagship failed, no CV in common rarity.')
            self._dock_reset()
            self.ui_back(check_button=FLEET_PREPARATION)
            return False

    def vanguard_change_hard(self):
        self.goto_fleet_hard()
        if self.is_ship_in_use(3):
            if self.change_vanguard_equip:
                logger.hr('Take off vanguard equipment', level=2)
                self.ship_info_enter(HARD_FLEET_GRIDS[(3, self.hard_grid_y)], long_click=True)
                self.ship_equipment_take_off()
                self.ui_back(FLEET_PREPARATION)
            self.ui_click(HARD_FLEET_GRIDS[(3, self.hard_grid_y)],
                          appear_button=FLEET_PREPARATION, check_button=DOCK_CHECK, skip_first_screenshot=True)
            self.ui_click(CARD_GRIDS[(0, 0)],
                          appear_button=DOCK_CHECK, check_button=FLEET_PREPARATION, skip_first_screenshot=True)
        self.ui_click(HARD_FLEET_GRIDS[(3 + self.config.GemsFarming_HardVanguardIndex, self.hard_grid_y)],
                      appear_button=FLEET_PREPARATION, check_button=DOCK_CHECK, skip_first_screenshot=True)
        if self.config.GemsFarming_CommonDD == 'any':
            faction = ['eagle', 'iron']
        elif self.config.GemsFarming_CommonDD == 'favourite':
            faction = 'all'
        elif self.config.GemsFarming_CommonDD == 'z20_or_z21':
            faction = 'iron'
        elif self.config.GemsFarming_CommonDD in ['aulick_or_foote', 'cassin_or_downes']:
            faction = 'eagle'
        else:
            logger.error(f'Invalid CommonDD setting: {self.config.GemsFarming_CommonDD}')
            raise ScriptError('Invalid GemsFarming_CommonDD')
        self.dock_filter_set(
            index='dd', rarity='common', faction=faction, extra='can_limit_break')
        self.dock_favourite_set(False)

        ships = self.get_common_rarity_dd()
        if ships:
            ship = max(ships, key=lambda s: s.emotion)
            self._new_emotion_value = min(ship.emotion, self._new_emotion_value)
            self.dock_select_one(ship.button)
            self._dock_reset()
            self.dock_select_confirm(check_button=FLEET_PREPARATION)
            logger.info('Change vanguard ship success')

            if self.change_vanguard_equip:
                logger.hr('Equip vanguard equipment', level=2)
                self.ship_info_enter(HARD_FLEET_GRIDS[(3, self.hard_grid_y)], long_click=True)
                self.ship_equipment_take_on_preset(1)
                self.ui_back(FLEET_PREPARATION)
            return True
        else:
            logger.info('Change vanguard ship failed, no DD in common rarity.')
            self._dock_reset()
            self.ui_back(check_button=FLEET_PREPARATION)
            return False

    def flagship_change(self):
        """
        Change flagship and flagship's equipment
        If config.GemsFarming_CommonCV == 'any', only change auxiliary equipment

        Returns:
            bool: True if flagship changed.
        """

        if self.is_hard_mode:
            return self.flagship_change_hard()

        if self.config.GemsFarming_CommonCV == 'any':
            index_list = range(3, 5)
        else:
            index_list = range(0, 5)
        logger.hr('Change flagship', level=1)
        logger.attr('ChangeFlagship', self.config.GemsFarming_ChangeFlagship)
        self.fleet_enter(self.fleet_to_attack)
        if self.change_flagship_equip:
            logger.hr('Record flagship equipment', level=2)
            self.fleet_enter_ship(FLEET_DETAIL_ENTER_FLAGSHIP)
            self.ship_equipment_record_image(index_list=index_list)
            self.ship_equipment_take_off()
            self.fleet_back()

        logger.hr('Change flagship', level=2)
        success = self.flagship_change_execute()

        if self.change_flagship_equip:
            logger.hr('Equip flagship equipment', level=2)
            self.fleet_enter_ship(FLEET_DETAIL_ENTER_FLAGSHIP)
            self.ship_equipment_take_off()
            self.ship_equipment_take_on_image(index_list=index_list)
            self.fleet_back()

        return success

    def vanguard_change(self):
        """
        Change vanguard and vanguard's equipment

        Returns:
            bool: True if vanguard changed
        """

        if self.is_hard_mode:
            return self.vanguard_change_hard()

        logger.hr('Change vanguard', level=1)
        logger.attr('ChangeVanguard', self.config.GemsFarming_ChangeVanguard)
        self.fleet_enter(self.fleet_to_attack)
        if self.change_vanguard_equip:
            logger.hr('Record vanguard equipment', level=2)
            self.fleet_enter_ship(FLEET_DETAIL_ENTER)
            self.ship_equipment_take_off()
            self.fleet_back()

        logger.hr('Change vanguard', level=2)
        success = self.vanguard_change_execute()

        if self.change_vanguard_equip:
            logger.hr('Equip vanguard equipment', level=2)
            self.fleet_enter_ship(FLEET_DETAIL_ENTER)
            self.ship_equipment_take_on_preset(1)
            self.fleet_back()

        return success

    def _dock_reset(self):
        self.dock_filter_set()
        self.dock_favourite_set(False)
        self.dock_sort_method_dsc_set()

    def _ship_change_confirm(self, button):

        self.dock_select_one(button)
        self._dock_reset()
        self.dock_select_confirm(check_button=page_fleet.check_button)

    @property
    def emotion_lower_bound(self):
        return 3 + EMOTION_LIMIT + self.campaign._map_battle * 2

    def get_common_rarity_cv(self):
        """
        Get a common rarity cv by config.GemsFarming_CommonCV
        If config.GemsFarming_CommonCV == 'any', return a common lv1 ~ lv33 cv
        Returns:
            Ship:
        """

        logger.hr('FINDING FLAGSHIP')

        scanner = ShipScanner(level=(1, 25), emotion=(self.emotion_lower_bound, 150),
                              fleet=self.fleet_to_attack, status='free')
        scanner.disable('rarity')

        if self.config.GemsFarming_CommonCV == 'any':

            self.dock_sort_method_dsc_set(False)

            ships = scanner.scan(self.device.image)
            if ships:
                # Don't need to change current
                return ships

            scanner.set_limitation(fleet=0)
            return scanner.scan(self.device.image, output=False)

        else:
            template = {
                'BOGUE': TEMPLATE_BOGUE,
                'HERMES': TEMPLATE_HERMES,
                'LANGLEY': TEMPLATE_LANGLEY,
                'RANGER': TEMPLATE_RANGER
            }[f'{self.config.GemsFarming_CommonCV.upper()}']

            self.dock_sort_method_dsc_set()

            ships = scanner.scan(self.device.image)
            if ships:
                # Don't need to change current
                return ships

            scanner.set_limitation(fleet=0)
            candidates = [ship for ship in scanner.scan(self.device.image, output=False)
                          if template.match(self.image_crop(ship.button, copy=False), similarity=SIM_VALUE)]

            if candidates:
                return candidates

            logger.info('No specific CV was found, try reversed order.')
            self.dock_sort_method_dsc_set(False)

            candidates = [ship for ship in scanner.scan(self.device.image)
                          if template.match(self.image_crop(ship.button, copy=False), similarity=SIM_VALUE)]

            return candidates

    def get_common_rarity_dd(self):
        """
        Get a common rarity dd with level is 100 (70 for servers except CN)
        and emotion >= self.emotion_lower_bound
        Returns:
            Ship:
        """
        logger.hr('FINDING VANGUARD')

        if self.config.SERVER in ['cn']:
            max_level = 100
        else:
            max_level = 70

        scanner = ShipScanner(level=(max_level, max_level), emotion=(self.emotion_lower_bound, 150),
                              fleet=self.fleet_to_attack, status='free')
        scanner.disable('rarity')

        self.dock_sort_method_dsc_set()

        if not self.change_vanguard:
            return scanner.scan(self.device.image)

        scanner.set_limitation(fleet=[0, self.fleet_to_attack])
        self.dock_favourite_set(self.config.GemsFarming_CommonDD == 'favourite')

        if self.config.GemsFarming_CommonDD in ['any', 'favourite', 'z20_or_z21']:
            return scanner.scan(self.device.image)

        candidates = self.find_candidates(self.get_templates(self.config.GemsFarming_CommonDD), scanner)

        if candidates:
            return candidates
        
        logger.info('No specific DD was found, try reversed order.')
        self.dock_sort_method_dsc_set(False)

        candidates = self.find_candidates(self.get_templates(self.config.GemsFarming_CommonDD), scanner)

        return candidates

    def find_candidates(self, template, scanner):
        """
        Find candidates based on template matching using a scanner.

        """
        candidates = []
        for item in template:
            candidates = [ship for ship in scanner.scan(self.device.image, output=False)
                          if item.match(self.image_crop(ship.button, copy=False), similarity=SIM_VALUE)]
            if candidates:
                break
        return candidates

    @staticmethod
    def get_templates(common_dd):
        """
        Returns the corresponding template list based on CommonDD
        """
        if common_dd == 'aulick_or_foote':
            return [
                TEMPLATE_AULICK,
                TEMPLATE_FOOTE
            ]
        elif common_dd == 'cassin_or_downes':
            return [
                TEMPLATE_CASSIN_1, TEMPLATE_CASSIN_2,
                TEMPLATE_DOWNES_1, TEMPLATE_DOWNES_2
            ]
        else:
            logger.error(f'Invalid CommonDD setting: {common_dd}')
            raise ScriptError(f'Invalid CommonDD setting: {common_dd}')

    def flagship_change_execute(self):
        """
        Returns:
            bool: If success.

        Pages:
            in: page_fleet
            out: page_fleet
        """
        self.ui_click(FLEET_ENTER_FLAGSHIP,
                      appear_button=page_fleet.check_button, check_button=DOCK_CHECK, skip_first_screenshot=True)
        self.dock_filter_set(
            index='cv', rarity='common', extra='enhanceable', sort='total')
        self.dock_favourite_set(False)

        ships = self.get_common_rarity_cv()
        if ships:
            ship = min(ships, key=lambda s: (s.level, -s.emotion))
            self._new_emotion_value = min(ship.emotion, self._new_emotion_value)
            self._ship_change_confirm(ship.button)

            logger.info('Change flagship success')
            return True
        else:
            logger.info('Change flagship failed, no CV in common rarity.')
            self._dock_reset()
            self.ui_back(check_button=page_fleet.check_button)
            return False

    def vanguard_change_execute(self):
        """
        Returns:
            bool: If success.

        Pages:
            in: page_fleet
            out: page_fleet
        """
        self.ui_click(FLEET_ENTER,
                      appear_button=page_fleet.check_button, check_button=DOCK_CHECK, skip_first_screenshot=True)

        if self.config.GemsFarming_CommonDD == 'any':
            faction = ['eagle', 'iron']
        elif self.config.GemsFarming_CommonDD == 'favourite':
            faction = 'all'
        elif self.config.GemsFarming_CommonDD == 'z20_or_z21':
            faction = 'iron'
        elif self.config.GemsFarming_CommonDD in ['aulick_or_foote', 'cassin_or_downes']:
            faction = 'eagle'
        else:
            logger.error(f'Invalid CommonDD setting: {self.config.GemsFarming_CommonDD}')
            raise ScriptError('Invalid GemsFarming_CommonDD')
        self.dock_filter_set(
            index='dd', rarity='common', faction=faction, extra='can_limit_break')
        self.dock_favourite_set(False)

        ships = self.get_common_rarity_dd()
        if ships:
            ship = max(ships, key=lambda s: s.emotion)
            self._new_emotion_value = min(ship.emotion, self._new_emotion_value)
            self._ship_change_confirm(ship.button)

            logger.info('Change vanguard ship success')
            return True
        else:
            logger.info('Change vanguard ship failed, no DD in common rarity.')
            self._dock_reset()
            self.ui_back(check_button=page_fleet.check_button)
            return False

    _trigger_lv32 = False
    _trigger_emotion = False

    def triggered_stop_condition(self, oil_check=True):
        # Lv32 limit
        if self.change_flagship and self.campaign.config.LV32_TRIGGERED:
            self._trigger_lv32 = True
            logger.hr('TRIGGERED LV32 LIMIT')
            return True

        if self.campaign.map_is_auto_search and self.campaign.config.GEMS_EMOTION_TRIGGRED:
            self._trigger_emotion = True
            logger.hr('TRIGGERED EMOTION LIMIT')
            return True

        return super().triggered_stop_condition(oil_check=oil_check)

    def run(self, name, folder='campaign_main', mode='normal', total=0):
        """
        Args:
            name (str): Name of .py file.
            folder (str): Name of the file folder under campaign.
            mode (str): `normal` or `hard`
            total (int):
        """

        if self.config.GemsFarming_CorrectEmotion:
            with self.config.multi_set():
                self.config.GemsFarming_CorrectEmotion = False
                self.set_emotion(0)

        now = datetime.now().replace(microsecond=0)
        try:
            target = self.config.GemsFarming_DelayUntil.strftime("%H:%M")
            target = get_server_next_update(target)
        except Exception as e:
            logger.warning(e)
            logger.warning('Delay until 05:00')
            target = get_server_next_update('05:00')
        if now.time() < target.time():
            self.config.task_delay(target=target)
            self.config.task_stop()

        self.config.STOP_IF_REACH_LV32 = self.change_flagship
        self.config.RETIRE_KEEP_COMMON_CV = True

        while 1:
            self._trigger_lv32 = False

            try:
                super().run(name=name, folder=folder, total=total)
            except CampaignEnd as e:
                if e.args[0] == 'Emotion withdraw' or e.args[0] == 'Emotion control':
                    self._trigger_emotion = True
                elif e.args[0] == 'Hard not satisfied':
                    if not self.is_hard_mode or not self.appear(FLEET_PREPARATION, offset=(20, 50)):
                        raise RequestHumanTakeover
                    elif self.is_ship_in_use(0) and self.is_ship_in_use(3):
                        raise RequestHumanTakeover
                    else:
                        self._trigger_emotion = True
                else:
                    raise e

            # End
            if self._trigger_lv32 or self._trigger_emotion:
                self._new_emotion_value = 150
                success = self.vanguard_change()
                if self.change_flagship:
                    success = success and self.flagship_change()
                if success and self.config.Emotion_Mode != 'ignore':
                    self.set_emotion(self._new_emotion_value)

                self._trigger_lv32 = False
                self._trigger_emotion = False
                self.campaign.config.LV32_TRIGGERED = False
                self.campaign.config.GEMS_EMOTION_TRIGGRED = False

                # Scheduler
                if not success:
                    self.campaign.ensure_auto_search_exit()
                    self.config.task_delay(minute=30)
                    self.config.task_stop()
                elif self.config.task_switched():
                    self.campaign.ensure_auto_search_exit()
                    self.config.task_stop()

                continue
            else:
                break
