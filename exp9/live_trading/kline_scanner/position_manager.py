class PositionManager:
    def __init__(self):
        self.position = False
        self.entry_price = 0.0
        self.stop_loss = 0.0
        self.target = 0.0
        self.entry_time = ""
        self.entry_bar_idx = 0
        self.h1_entry_idx = 0
        self.max_price = 0.0
        self.atr = 0.0
        self.atr_1h = 0.0
        self.stage = None
        self.grade = None
        self.lot1_done = False
        self.lot2_stop = 0.0

    def enter(self, entry_price, stop_loss, target, entry_time, entry_bar_idx, atr=0.0, stage=None, grade=None, h1_entry_idx=0):
        self.position = True
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.target = target
        self.entry_time = entry_time
        self.entry_bar_idx = entry_bar_idx
        self.h1_entry_idx = h1_entry_idx
        self.max_price = entry_price
        self.atr = atr
        self.atr_1h = 0.0
        self.stage = stage
        self.grade = grade
        self.lot1_done = False
        self.lot2_stop = stop_loss

    def exit(self, exit_price, reason, exit_time):
        profit = (exit_price - self.entry_price) / self.entry_price * 100
        trade = {
            "entry_time": self.entry_time,
            "entry_price": self.entry_price,
            "exit_time": exit_time,
            "exit_price": exit_price,
            "profit": profit,
            "profit_pct": profit,
            "reason": reason,
            "stage": self.stage,
            "grade": self.grade,
        }
        self.position = False
        self.entry_price = 0.0
        self.stop_loss = 0.0
        self.target = 0.0
        return trade

    def update_stop_loss(self, new_stop):
        self.stop_loss = new_stop
        self.lot2_stop = new_stop

    def update_max_price(self, price):
        if price > self.max_price:
            self.max_price = price

    def set_peak_price(self, price):
        self.max_price = price

    def mark_lot1_done(self):
        self.lot1_done = True

    def is_in_position(self):
        return self.position

    def get_position_info(self):
        return {
            "position": self.position,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "entry_time": self.entry_time,
            "entry_bar_idx": self.entry_bar_idx,
            "h1_entry_idx": self.h1_entry_idx,
            "max_price": self.max_price,
            "peak_price": self.max_price,
            "atr": self.atr,
            "atr_1h": self.atr_1h,
            "stage": self.stage,
            "grade": self.grade,
            "lot1_done": self.lot1_done,
            "lot2_stop": self.lot2_stop,
            "ticker": ""
        }
