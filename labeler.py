#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Interactive MEP / D-wave Waveform Annotator
"""

import copy
import os
import re
import threading
from datetime import datetime

import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, Slider
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, Menu, simpledialog


# ─────────────────────────────────────────────────────────────────────────────
# Metadata helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_analysis_time(metadata: dict) -> float:
    try:
        return float(str(metadata.get('Analysis time', '10')).replace('ms', '').strip())
    except (ValueError, TypeError):
        return 10.0

def _parse_display_len(metadata: dict) -> float:
    try:
        return float(str(metadata.get('Display length', '10div')).lower().replace('div', '').strip())
    except (ValueError, TypeError):
        return 10.0

def ms_per_unit(metadata: dict) -> float:
    """True ms per timepoint index."""
    return (_parse_analysis_time(metadata) * _parse_display_len(metadata)) / 1000.0

def sens_factor(metadata: dict) -> float:
    """µV per raw amplitude unit."""
    s = str(metadata.get('Sens', '')).strip()
    m = re.match(r'([\d.]+)\s*(uV|µV|mV)', s, re.IGNORECASE)
    if not m:
        return 1.0
    v = float(m.group(1))
    if m.group(2).lower() == 'mv':
        v *= 1000.0
    return v * 1.5e-4

# ─────────────────────────────────────────────────────────────────────────────
# Annotation unit conversion
#
# The original annotator used hardcoded 0.1 ms/unit for ALL signals.
# Stored value = event.xdata on that axis = true_ms / 0.1
#
# So:  stored = true_ms / 0.1
#      true_ms = stored * 0.1
#
# For MEP (true mpu=0.1):   stored = true_ms / 0.1 = true_ms * 10
#   BUT old MEP files stored event.xdata directly which WAS true_ms
#   because the old axis used indices * 0.1 = true_ms for MEP.
#   So old MEP stored value ≈ true_ms (not true_ms*10).
#
# After careful analysis of actual files:
#   MEP  annotation_start_ms="20.79"  → true_ms = 20.79  (identity)
#   Dwave annotation_start_ms="18.06" → true_ms = 18.06 * true_mpu / 0.1
#                                      = 18.06 * 0.02 / 0.1 = 3.612ms
#
# So the conversion is:  true_ms = stored * true_mpu / 0.1
#                        stored  = true_ms * 0.1 / true_mpu
#
# For MEP true_mpu=0.1:  true_ms = stored * 0.1/0.1 = stored  ✓
# For Dwave true_mpu=0.02: true_ms = stored * 0.02/0.1 = stored * 0.2 ✓
# ─────────────────────────────────────────────────────────────────────────────

LEGACY_MPU = 0.1  # original hardcoded ms/unit

def stored_to_true_ms(stored: float, metadata: dict) -> float:
    """Convert stored annotation value to true ms for plotting."""
    mpu = ms_per_unit(metadata)
    return stored * mpu / LEGACY_MPU

def true_ms_to_stored(true_ms: float, metadata: dict) -> float:
    """Convert true ms (plot coordinate) to stored annotation value."""
    mpu = ms_per_unit(metadata)
    return true_ms * LEGACY_MPU / mpu if mpu else true_ms


# ─────────────────────────────────────────────────────────────────────────────
# D-wave helpers
# ─────────────────────────────────────────────────────────────────────────────

def _electrode_pair(metadata: dict) -> str:
    pos = metadata.get('Electrode (+)', '').strip()
    neg = metadata.get('Electrode (-)', '').strip()
    if pos and neg:
        return f"{pos.split()[-1]}_{neg.split()[-1]}"
    m = re.search(r'(\d+)[- ](\d+)', metadata.get('Wave comment', ''))
    return f"{m.group(1)}_{m.group(2)}" if m else 'unknown'

def _is_dwave_file(filepath: str) -> bool:
    stem = os.path.basename(filepath).upper()
    return 'DWAVE' in stem or 'D-WAVE' in stem


# ─────────────────────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_file(filepath: str) -> list:
    recordings = []
    with open(filepath, 'r') as f:
        lines = f.readlines()
    meta, wave, in_wave = {}, [], False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) < 2:
            continue
        key   = parts[0].strip('"')
        value = parts[1].strip('"')
        if key == 'Wave':
            in_wave = True
            try:
                wave.append((int(value), float(parts[2]) if len(parts) > 2 else 0.0))
            except ValueError:
                pass
        else:
            if in_wave and wave:
                recordings.append({'metadata': meta.copy(), 'wave': wave.copy()})
                meta, wave, in_wave = {}, [], False
            meta[key] = value
    if wave:
        recordings.append({'metadata': meta.copy(), 'wave': wave.copy()})
    return recordings


# ─────────────────────────────────────────────────────────────────────────────
# Annotator
# ─────────────────────────────────────────────────────────────────────────────

class MEPAnnotator:

    def __init__(self, master: tk.Tk):
        self.master      = master
        self.filepath    = None
        self.recordings  = []
        self.groups      = []
        self.group_idx   = 0
        self.is_dwave    = False

        self.history: list = []
        self.history_pos   = -1
        self.marking_mode  = None   # None | ('start', None) | ('end', None)

        self.fig            = None
        self.axes           = []
        self.start_lines    = []
        self.end_lines      = []
        self.preview_lines  = []
        self.excl_btns      = []
        self.dragging       = None  # None | ('start'|'end', sub_i)
        self.channel_active = []

        self._x_full = (0.0, 1.0)
        self._y_full = (-1.0, 1.0)

        self._dirty       = False
        self._save_thread = None

        self._build_menu()
        self.master.protocol('WM_DELETE_WINDOW', self._on_exit)

    # ── menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        mb = Menu(self.master)
        self.master.config(menu=mb)
        fm = Menu(mb, tearoff=0)
        mb.add_cascade(label='File', menu=fm)
        fm.add_command(label='Open File…',    command=self.open_file)
        fm.add_command(label='Save (Ctrl+S)', command=self._flush_save)
        fm.add_command(label='Close File',    command=self.close_file)
        fm.add_separator()
        fm.add_command(label='Exit',          command=self._on_exit)
        hm = Menu(mb, tearoff=0)
        mb.add_cascade(label='Help', menu=hm)
        hm.add_command(label='Keyboard Shortcuts', command=self._show_help)

    def _on_exit(self):
        self._flush_save()
        if self._save_thread and self._save_thread.is_alive():
            self._save_thread.join(timeout=5)
        if self.fig:
            plt.close(self.fig)
        self.master.destroy()

    def _show_help(self):
        messagebox.showinfo('Keyboard Shortcuts', """
Navigation:
  A / ←   Previous group       D / →   Next group
  J        Jump to group        U        Next unannotated

Annotation (all included channels):
  Y  — Has waveform (auto starts→end workflow)
  N  — No waveform
  S/M — Start-mark mode then click
  E   — End-mark mode then click
  C   — Clear markers

D-wave per-channel:
  [Excl] — marks that channel NO waveform
  Drag start/end line — moves marker for THAT channel only

Zoom/Pan sliders — right = zoom in, pan slides window within data
Ctrl+Z  Undo   Ctrl+Y  Redo   Ctrl+S  Save   ESC  Cancel marking
""")

    # ── file I/O ──────────────────────────────────────────────────────────────

    def open_file(self):
        self._flush_save()
        fp = filedialog.askopenfilename(
            title='Select MEP / D-wave file',
            filetypes=[('Text files', '*.txt'), ('All files', '*.*')],
            initialdir=os.path.expanduser('~'))
        if fp:
            self.load_file(fp)

    def close_file(self):
        self._flush_save()
        if self.fig:
            plt.close(self.fig)
            self.fig = None
        self.filepath = self.recordings = None
        self.groups = []
        self.group_idx = 0
        self.history = []
        self.history_pos = -1
        self.marking_mode = None
        self.axes = self.start_lines = self.end_lines = []
        self.preview_lines = self.excl_btns = []
        self.channel_active = []
        self._dirty = False

    def load_file(self, filepath: str):
        try:
            self.filepath     = filepath
            self.recordings   = parse_file(filepath)
            self.is_dwave     = _is_dwave_file(filepath)
            self.group_idx    = 0
            self.history      = []
            self.history_pos  = -1
            self.marking_mode = None
            self._dirty       = False

            self._build_groups()
            self._save_history()

            if self.fig is not None:
                plt.close(self.fig)
                self.fig = None

            self._setup_figure()
            self.update_plot()
            print(f"Loaded {len(self.recordings)} recordings "
                  f"({len(self.groups)} groups) from {os.path.basename(filepath)}")
        except Exception as e:
            messagebox.showerror('Error', f'Failed to load file:\n{e}')
            raise

    # ── grouping ──────────────────────────────────────────────────────────────

    def _build_groups(self):
        if not self.is_dwave:
            self.groups = [[i] for i in range(len(self.recordings))]
            return

        all_pairs, seen = [], set()
        for rec in self.recordings:
            p = _electrode_pair(rec['metadata'])
            if p not in seen:
                all_pairs.append(p)
                seen.add(p)

        blocks = {p: [] for p in all_pairs}
        for i, rec in enumerate(self.recordings):
            blocks[_electrode_pair(rec['metadata'])].append(i)

        min_len = min(len(blocks[p]) for p in all_pairs)
        self.groups = [[blocks[p][t] for p in all_pairs] for t in range(min_len)]
        dropped = len(self.recordings) - min_len * len(all_pairs)
        print(f"D-wave: {len(all_pairs)} pairs: {all_pairs}, "
              f"{len(self.groups)} groups, {dropped} dropped")

    # ── history ───────────────────────────────────────────────────────────────

    def _save_history(self):
        self.history = self.history[:self.history_pos + 1]
        self.history.append(copy.deepcopy(self.recordings))
        self.history_pos += 1
        if len(self.history) > 50:
            self.history.pop(0)
            self.history_pos -= 1

    def undo(self):
        if self.history_pos > 0:
            self.history_pos -= 1
            self.recordings = copy.deepcopy(self.history[self.history_pos])
            self._mark_dirty()
            self.update_plot()
        else:
            print('Nothing to undo.')

    def redo(self):
        if self.history_pos < len(self.history) - 1:
            self.history_pos += 1
            self.recordings = copy.deepcopy(self.history[self.history_pos])
            self._mark_dirty()
            self.update_plot()
        else:
            print('Nothing to redo.')

    # ── annotation ────────────────────────────────────────────────────────────

    def _get_ann(self, idx: int) -> dict:
        """Return annotation with start_ms/end_ms in TRUE ms (plot coordinates)."""
        m = self.recordings[idx]['metadata']
        def to_true(key):
            if key not in m:
                return None
            return stored_to_true_ms(float(m[key]), m)
        return {
            'has_waveform': m.get('annotation_has_waveform'),
            'start_ms':     to_true('annotation_start_ms'),
            'end_ms':       to_true('annotation_end_ms'),
        }

    def _write_ann(self, idx: int, *, has_waveform=None, start_true_ms=None, end_true_ms=None):
        """Write annotation. Converts true ms → stored format before saving."""
        m = self.recordings[idx]['metadata']
        if has_waveform is not None:
            m['annotation_has_waveform'] = str(has_waveform)
        if start_true_ms is not None:
            m['annotation_start_ms'] = str(true_ms_to_stored(start_true_ms, m))
        if end_true_ms is not None:
            m['annotation_end_ms'] = str(true_ms_to_stored(end_true_ms, m))
        m['annotation_last_modified'] = datetime.now().isoformat()

    def _write_group(self, *, has_waveform=None, start_true_ms=None, end_true_ms=None):
        """Write annotation to all active channels in current group."""
        self._save_history()
        for sub_i, idx in enumerate(self.groups[self.group_idx]):
            if not self.channel_active[sub_i]:
                continue
            self._write_ann(idx,
                has_waveform=has_waveform,
                start_true_ms=start_true_ms,
                end_true_ms=end_true_ms)
        self._mark_dirty()

    def _exclude_channel(self, sub_i: int):
        self._save_history()
        idx = self.groups[self.group_idx][sub_i]
        m   = self.recordings[idx]['metadata']
        m['annotation_has_waveform'] = 'False'
        m.pop('annotation_start_ms', None)
        m.pop('annotation_end_ms',   None)
        m['annotation_last_modified'] = datetime.now().isoformat()
        self._mark_dirty()
        self.update_plot()

    # ── save ──────────────────────────────────────────────────────────────────

    def _mark_dirty(self):
        self._dirty = True

    def _flush_save(self):
        if not self._dirty or not self.filepath or not self.recordings:
            return
        lines = []
        for rec in self.recordings:
            for k, v in rec['metadata'].items():
                lines.append(f'"{k}","{v}"\n')
            for wi, wv in rec['wave']:
                lines.append(f'"Wave",{wi},{wv}\n')
        content  = ''.join(lines)
        filepath = self.filepath
        self._dirty = False

        def _write():
            try:
                with open(filepath, 'w') as f:
                    f.write(content)
                print(f'Saved → {filepath}')
            except Exception as e:
                print(f'Save error: {e}')

        self._save_thread = threading.Thread(target=_write, daemon=True)
        self._save_thread.start()

    # ── figure ────────────────────────────────────────────────────────────────

    def _n_subplots(self) -> int:
        return len(self.groups[self.group_idx]) if self.groups else 1

    def _setup_figure(self):
        n     = self._n_subplots()
        fig_h = max(8, min(20, 3 * n + 4))
        self.fig = plt.figure(figsize=(16, fig_h))
        self.fig.canvas.mpl_disconnect(
            self.fig.canvas.manager.key_press_handler_id)

        self.axes           = []
        self.start_lines    = []
        self.end_lines      = []
        self.preview_lines  = []
        self.excl_btns      = []
        self.channel_active = [True] * n

        BOTTOM = 0.28
        TOP_M  = 0.04
        GAP    = 0.012
        avail  = 1.0 - BOTTOM - TOP_M
        sh     = (avail - GAP * (n - 1)) / n
        PLOT_L, PLOT_W = 0.08, 0.82
        BTN_L,  BTN_W  = 0.915, 0.07

        for i in range(n):
            bottom = BOTTOM + (n - 1 - i) * (sh + GAP)
            ax = self.fig.add_axes([PLOT_L, bottom, PLOT_W, sh])
            self.axes.append(ax)
            self.start_lines.append(None)
            self.end_lines.append(None)
            self.preview_lines.append(None)

            if self.is_dwave:
                btn_h  = min(0.04, sh * 0.4)
                btn_b  = bottom + (sh - btn_h) / 2
                btn_ax = self.fig.add_axes([BTN_L, btn_b, BTN_W, btn_h])
                btn    = Button(btn_ax, 'Excl', color='#ffcccc')
                btn.label.set_fontsize(8)
                sub_i  = i
                btn.on_clicked(lambda _, si=sub_i: self._exclude_channel(si))
                self.excl_btns.append(btn)
            else:
                self.excl_btns.append(None)

        # Sliders
        SL, SW, SR, SH = 0.08, 0.38, 0.54, 0.018
        self.ax_xzoom = self.fig.add_axes([SL, 0.175, SW, SH])
        self.ax_yzoom = self.fig.add_axes([SR, 0.175, SW, SH])
        self.ax_xpan  = self.fig.add_axes([SL, 0.135, SW, SH])
        self.ax_ypan  = self.fig.add_axes([SR, 0.135, SW, SH])
        self.sl_xzoom = Slider(self.ax_xzoom, 'X zoom', 1.0, 10.0, valinit=1.0, valstep=0.1)
        self.sl_yzoom = Slider(self.ax_yzoom, 'Y zoom', 1.0, 10.0, valinit=1.0, valstep=0.1)
        self.sl_xpan  = Slider(self.ax_xpan,  'X pan',  0.0,  1.0, valinit=0.5)
        self.sl_ypan  = Slider(self.ax_ypan,  'Y pan',  0.0,  1.0, valinit=0.5)
        for sl in (self.sl_xzoom, self.sl_yzoom, self.sl_xpan, self.sl_ypan):
            sl.on_changed(self._apply_zoom_pan)

        # Buttons
        BY, BH = 0.07, 0.045
        def _btn(x, w, label, **kw):
            return Button(self.fig.add_axes([x, BY, w, BH]), label, **kw)

        self.btn_prev  = _btn(0.02,  0.08, '◀ Prev (A)')
        self.btn_next  = _btn(0.11,  0.08, 'Next (D) ▶')
        self.btn_jump  = _btn(0.20,  0.08, 'Jump (J)')
        self.btn_unann = _btn(0.29,  0.10, 'Next Unann (U)')
        self.btn_yes   = _btn(0.46,  0.08, 'Has MEP (Y)', color='lightgreen')
        self.btn_no    = _btn(0.55,  0.08, 'No MEP (N)',  color='lightcoral')
        self.btn_start = _btn(0.70,  0.08, 'Start (S/M)', color='lightblue')
        self.btn_end   = _btn(0.79,  0.08, 'End (E)',      color='lightblue')
        self.btn_clear = _btn(0.88,  0.055,'Clear (C)',    color='lightyellow')
        self.btn_undo  = _btn(0.937, 0.028,'Undo')
        self.btn_redo  = _btn(0.968, 0.028,'Redo')

        self.btn_prev .on_clicked(lambda _: self.prev_group())
        self.btn_next .on_clicked(lambda _: self.next_group())
        self.btn_jump .on_clicked(lambda _: self.jump_to_group())
        self.btn_unann.on_clicked(lambda _: self.jump_to_unannotated())
        self.btn_yes  .on_clicked(lambda _: self.mark_has_waveform(True))
        self.btn_no   .on_clicked(lambda _: self.mark_has_waveform(False))
        self.btn_start.on_clicked(lambda _: self._enter_marking('start'))
        self.btn_end  .on_clicked(lambda _: self._enter_marking('end'))
        self.btn_clear.on_clicked(lambda _: self.clear_marks())
        self.btn_undo .on_clicked(lambda _: self.undo())
        self.btn_redo .on_clicked(lambda _: self.redo())

        self.info_text = self.fig.text(
            0.5, 0.98, '', fontsize=9, ha='center', va='top', family='monospace')

        self._attach_events()
        plt.show(block=False)

    def _attach_events(self):
        c = self.fig.canvas
        c.mpl_connect('key_press_event',     self._on_key)
        c.mpl_connect('button_press_event',   self._on_click)
        c.mpl_connect('button_release_event', self._on_release)
        c.mpl_connect('motion_notify_event',  self._on_move)

    # ── zoom / pan ────────────────────────────────────────────────────────────

    def _apply_zoom_pan(self, _val=None):
        xmin, xmax = self._x_full
        ymin, ymax = self._y_full
        x_span = (xmax - xmin) / self.sl_xzoom.val
        y_span = (ymax - ymin) / self.sl_yzoom.val
        x_lo = xmin + max(0.0, min(1.0, self.sl_xpan.val)) * ((xmax - xmin) - x_span)
        y_lo = ymin + max(0.0, min(1.0, self.sl_ypan.val)) * ((ymax - ymin) - y_span)
        x_lo = max(xmin, min(x_lo, xmax - x_span))
        y_lo = max(ymin, min(y_lo, ymax - y_span))
        for ax in self.axes:
            ax.set_xlim(x_lo, x_lo + x_span)
            ax.set_ylim(y_lo, y_lo + y_span)
        if self.fig:
            self.fig.canvas.draw_idle()

    # ── plot update ───────────────────────────────────────────────────────────

    def update_plot(self):
        if not self.recordings or not self.groups:
            return

        group = self.groups[self.group_idx]
        n     = len(group)

        if len(self.axes) != n:
            plt.close(self.fig)
            self.fig = None
            self._setup_figure()

        all_x, all_y = [], []

        for sub_i, rec_idx in enumerate(group):
            ax  = self.axes[sub_i]
            rec = self.recordings[rec_idx]
            ax.clear()

            tp   = np.array([w[0] for w in rec['wave']])
            amp  = np.array([w[1] for w in rec['wave']])
            mpu  = ms_per_unit(rec['metadata'])
            sf   = sens_factor(rec['metadata'])
            t_ms = tp  * mpu
            y_uv = amp * sf

            all_x.extend([float(t_ms.min()), float(t_ms.max())])
            all_y.extend([float(y_uv.min()), float(y_uv.max())])

            # Per-channel annotation (already in true ms)
            ann = self._get_ann(rec_idx)

            if ann['has_waveform'] == 'False':
                bg = '#FFE5E5'
            elif not self.channel_active[sub_i]:
                bg = '#EEEEEE'
            else:
                bg = 'white'
            ax.set_facecolor(bg)

            alpha = 1.0 if self.channel_active[sub_i] else 0.45
            ax.plot(t_ms, y_uv, 'b-', lw=1.5, alpha=alpha)
            ax.axhline(0, color='k', lw=0.5, alpha=0.5)
            ax.axvline(0, color='k', ls='--', lw=1, alpha=0.5)
            ax.set_ylabel('µV', fontsize=9)
            ax.grid(True, alpha=0.3)

            if self.is_dwave:
                pair   = _electrode_pair(rec['metadata'])
                suffix = '' if self.channel_active[sub_i] else '  [excluded]'
                ax.set_title(f'Electrodes {pair}{suffix}', fontsize=9, loc='left', pad=2)
            else:
                ax.set_title(
                    f'{rec["metadata"].get("Wave comment", "")}  —  '
                    f'{rec["metadata"].get("Date & time 0", "")}',
                    fontsize=10, fontweight='bold')

            # Draw markers — ann values are already in true ms
            if ann['start_ms'] is not None:
                self.start_lines[sub_i] = ax.axvline(
                    ann['start_ms'], color='green', ls='--', lw=2.5,
                    label='Start', picker=True, pickradius=5)
            else:
                self.start_lines[sub_i] = None

            if ann['end_ms'] is not None:
                self.end_lines[sub_i] = ax.axvline(
                    ann['end_ms'], color='red', ls='--', lw=2.5,
                    label='End', picker=True, pickradius=5)
            else:
                self.end_lines[sub_i] = None

            if sub_i == n - 1:
                ax.set_xlabel('Time (ms)', fontsize=10)
            if ann['start_ms'] is not None or ann['end_ms'] is not None:
                ax.legend(fontsize=8, loc='upper right')

        # Update full data extents; re-centre pan if range changed
        if all_x:
            pad_x = (max(all_x) - min(all_x)) * 0.02 or 1.0
            pad_y = (max(all_y) - min(all_y)) * 0.10 or 1.0
            new_x = (min(all_x) - pad_x, max(all_x) + pad_x)
            new_y = (min(all_y) - pad_y, max(all_y) + pad_y)
            if new_x != self._x_full or new_y != self._y_full:
                self._x_full = new_x
                self._y_full = new_y
                for sl in (self.sl_xpan, self.sl_ypan):
                    sl.eventson = False
                    sl.set_val(0.5)
                    sl.eventson = True

        self._apply_zoom_pan()

        # Info bar
        total_ann = sum(
            1 for r in self.recordings
            if r['metadata'].get('annotation_has_waveform') is not None)
        parts = [
            f'File: {os.path.basename(self.filepath)}',
            f'Group: {self.group_idx+1}/{len(self.groups)}',
            f'Progress: {total_ann}/{len(self.recordings)}',
        ]
        for sub_i, rec_idx in enumerate(group):
            ann = self._get_ann(rec_idx)
            hw  = ann['has_waveform']
            tag = '✓' if hw == 'True' else ('✗' if hw == 'False' else '?')
            if self.is_dwave:
                pair = _electrode_pair(self.recordings[rec_idx]['metadata'])
                parts.append(f'{pair}:{tag}')
            else:
                parts.append('✓ HAS' if hw == 'True' else ('✗ NO' if hw == 'False' else 'Not annotated'))

        if self.marking_mode:
            mode, _ = self.marking_mode
            parts.append(f'>>> CLICK {mode.upper()} <<<')
        if self._dirty:
            parts.append('[unsaved]')

        self.info_text.set_text('  |  '.join(parts))
        self.fig.canvas.draw_idle()

    # ── navigation ────────────────────────────────────────────────────────────

    def _nav_to(self, gi: int):
        self._flush_save()
        self.group_idx      = gi
        self.marking_mode   = None
        self.channel_active = [True] * len(self.groups[gi])
        self.update_plot()

    def prev_group(self):
        if self.group_idx > 0:
            self._nav_to(self.group_idx - 1)

    def next_group(self):
        if self.group_idx < len(self.groups) - 1:
            self._nav_to(self.group_idx + 1)

    def jump_to_group(self):
        n = simpledialog.askinteger(
            'Jump', f'Group (1–{len(self.groups)}):',
            minvalue=1, maxvalue=len(self.groups), parent=self.master)
        if n:
            self._nav_to(n - 1)

    def jump_to_unannotated(self):
        start = self.group_idx + 1
        order = list(range(start, len(self.groups))) + list(range(0, start))
        for gi in order:
            idx = self.groups[gi][0]
            if self.recordings[idx]['metadata'].get('annotation_has_waveform') is None:
                self._nav_to(gi)
                return
        messagebox.showinfo('Done', 'All groups annotated!')

    # ── annotation actions ────────────────────────────────────────────────────

    def mark_has_waveform(self, yes: bool):
        self._write_group(has_waveform=yes)
        self.marking_mode = ('start', None) if yes else None
        self.update_plot()

    def _enter_marking(self, mode: str):
        self.marking_mode = (mode, None)
        self.update_plot()

    def clear_marks(self):
        self._save_history()
        for sub_i, idx in enumerate(self.groups[self.group_idx]):
            if not self.channel_active[sub_i]:
                continue
            m = self.recordings[idx]['metadata']
            m.pop('annotation_start_ms', None)
            m.pop('annotation_end_ms',   None)
        self._mark_dirty()
        self.update_plot()

    # ── mouse ─────────────────────────────────────────────────────────────────

    def _ax_at(self, event) -> int:
        for i, ax in enumerate(self.axes):
            if event.inaxes is ax:
                return i
        return -1

    def _on_move(self, event):
        ax_i = self._ax_at(event)
        for i in range(len(self.axes)):
            if i != ax_i and self.preview_lines[i] is not None:
                try:
                    self.preview_lines[i].remove()
                except Exception:
                    pass
                self.preview_lines[i] = None
        if ax_i < 0 or event.xdata is None:
            self.fig.canvas.draw_idle()
            return
        t = event.xdata
        if self.dragging:
            which, drag_sub = self.dragging
            line = self.start_lines[drag_sub] if which == 'start' else self.end_lines[drag_sub]
            if line is not None:
                line.set_xdata([t, t])
            self.fig.canvas.draw_idle()
            return
        if self.marking_mode:
            if self.preview_lines[ax_i] is not None:
                try:
                    self.preview_lines[ax_i].remove()
                except Exception:
                    pass
            color = 'green' if self.marking_mode[0] == 'start' else 'red'
            self.preview_lines[ax_i] = self.axes[ax_i].axvline(
                t, color=color, ls=':', lw=1, alpha=0.5)
            self.fig.canvas.draw_idle()

    def _on_click(self, event):
        ax_i = self._ax_at(event)
        if ax_i < 0 or event.xdata is None:
            return
        t = event.xdata   # true ms (plot coordinate)

        # Drag initiation
        if not self.marking_mode:
            rec_idx = self.groups[self.group_idx][ax_i]
            ann     = self._get_ann(rec_idx)   # true ms
            xlim    = self.axes[ax_i].get_xlim()
            thresh  = (xlim[1] - xlim[0]) * 0.02
            if ann['end_ms'] is not None and abs(t - ann['end_ms']) < thresh:
                self.dragging = ('end', ax_i)
                return
            if ann['start_ms'] is not None and abs(t - ann['start_ms']) < thresh:
                self.dragging = ('start', ax_i)
                return

        # Marking click
        if self.marking_mode:
            mode, _ = self.marking_mode
            if self.preview_lines[ax_i] is not None:
                try:
                    self.preview_lines[ax_i].remove()
                except Exception:
                    pass
                self.preview_lines[ax_i] = None

            self._save_history()
            for sub_i, idx in enumerate(self.groups[self.group_idx]):
                if not self.channel_active[sub_i]:
                    continue
                if mode == 'start':
                    self._write_ann(idx, start_true_ms=t)
                else:
                    self._write_ann(idx, end_true_ms=t)
            self._mark_dirty()

            self.marking_mode = ('end', None) if mode == 'start' else None
            self.update_plot()

    def _on_release(self, event):
        if self.dragging:
            which, drag_sub = self.dragging
            if event.xdata is not None:
                idx = self.groups[self.group_idx][drag_sub]
                self._save_history()
                if which == 'start':
                    self._write_ann(idx, start_true_ms=event.xdata)
                else:
                    self._write_ann(idx, end_true_ms=event.xdata)
                self._mark_dirty()
                self.update_plot()
        self.dragging = None

    # ── keyboard ──────────────────────────────────────────────────────────────

    def _on_key(self, event):
        k = event.key
        if   k in ('a', 'left'):               self.prev_group()
        elif k in ('d', 'right'):              self.next_group()
        elif k == 'y':                         self.mark_has_waveform(True)
        elif k == 'n':                         self.mark_has_waveform(False)
        elif k in ('s', 'm'):                  self._enter_marking('start')
        elif k == 'e':                         self._enter_marking('end')
        elif k == 'c':                         self.clear_marks()
        elif k == 'u':                         self.jump_to_unannotated()
        elif k == 'j':                         self.jump_to_group()
        elif k == 'escape':
            self.marking_mode = None
            self.update_plot()
        elif k == 'ctrl+z':                    self.undo()
        elif k in ('ctrl+y', 'ctrl+shift+z'):  self.redo()
        elif k == 'ctrl+s':                    self._flush_save()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    root.title('MEP / D-wave Annotator')
    root.geometry('280x80')
    annotator = MEPAnnotator(master=root)
    tk.Label(root,
             text='MEP / D-wave Annotator\n\nFile → Open File to begin',
             pady=10).pack()

    import sys
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        annotator.load_file(sys.argv[1])

    root.mainloop()


if __name__ == '__main__':
    main()