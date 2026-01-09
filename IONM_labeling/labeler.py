#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Interactive MEP Waveform Annotator
Allows manual annotation of MEP latency start/end points with quality ratings
"""

import numpy as np
import matplotlib
matplotlib.use('TkAgg')  # Use TkAgg backend
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
import os
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, Menu

class MEPAnnotator:
    def __init__(self, master=None):
        self.master = master
        self.filepath = None
        self.recordings = None
        self.current_idx = 0
        self.history = []
        self.history_position = -1
        self.marking_mode = None
        self.fig = None
        self.ax = None
        
        # Create menu bar
        if master:
            self.create_menu()
        
    def create_menu(self):
        """Create menu bar"""
        menubar = Menu(self.master)
        self.master.config(menu=menubar)
        
        # File menu
        file_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open File...", command=self.open_file)
        file_menu.add_command(label="Close File", command=self.close_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.master.quit)
        
        # Help menu
        help_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Keyboard Shortcuts", command=self.show_help)
    
    def show_help(self):
        """Show help dialog with keyboard shortcuts"""
        help_text = """
MEP WAVEFORM ANNOTATOR - Keyboard Shortcuts

Navigation:
  A / Left Arrow  - Previous recording
  D / Right Arrow - Next recording
  J               - Jump to specific recording number
  U               - Jump to next completely unannotated recording

Annotation:
  Y - Mark as HAS waveform (auto-starts marking workflow)
  N - Mark as NO waveform
  
Marking Workflow (after pressing Y):
  1. Click to mark START point
  2. Click to mark END point
  (Workflow completes automatically)
  
Manual Marking / Editing:
  S or M - Mark start point (click on plot)
  E      - Mark end point (click on plot)
  C      - Clear markers
  
Edit:
  Ctrl+Z - Undo
  Ctrl+Y - Redo
  ESC    - Cancel marking mode
"""
        messagebox.showinfo("Help - Keyboard Shortcuts", help_text)
    
    def open_file(self):
        """Open file dialog to select MEP file"""
        filepath = filedialog.askopenfilename(
            title="Select MEP File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=os.path.expanduser("~")
        )
        
        if filepath:
            self.load_file(filepath)
    
    def close_file(self):
        """Close current file"""
        if self.fig:
            plt.close(self.fig)
            self.fig = None
            self.ax = None
        self.filepath = None
        self.recordings = None
        self.current_idx = 0
        self.history = []
        self.history_position = -1
        print("File closed")
    
    def load_file(self, filepath):
        """Load MEP file"""
        try:
            self.filepath = filepath
            self.recordings = self.parse_file(filepath)
            self.current_idx = 0
            self.history = []
            self.history_position = -1
            self.marking_mode = None
            
            # Save initial state
            self.save_to_history()
            
            # Setup or update plot
            if self.fig is None:
                self.setup_plot()
            
            self.update_plot()
            
            print(f"Loaded {len(self.recordings)} recordings from {os.path.basename(filepath)}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file:\n{str(e)}")
            raise
    
    def parse_file(self, filepath):
        """Parse MEP file and return all recordings"""
        recordings = []
        
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        current_metadata = {}
        current_wave = []
        in_wave_section = False
        
        for line in lines:
            line_text = line.strip()
            if not line_text:
                continue
                
            parts = line_text.split(',')
            if len(parts) >= 2:
                key = parts[0].strip('"')
                value = parts[1].strip('"')
                
                if key == "Wave":
                    in_wave_section = True
                    wave_index = int(value)
                    wave_value = float(parts[2]) if len(parts) > 2 else 0
                    current_wave.append((wave_index, wave_value))
                else:
                    if in_wave_section and current_wave:
                        recordings.append({
                            'metadata': current_metadata.copy(),
                            'wave': current_wave.copy()
                        })
                        current_metadata = {}
                        current_wave = []
                        in_wave_section = False
                    
                    current_metadata[key] = value
        
        if current_wave:
            recordings.append({
                'metadata': current_metadata.copy(),
                'wave': current_wave.copy()
            })
        
        return recordings
    
    def get_annotation(self, idx):
        """Get annotation from recording metadata"""
        metadata = self.recordings[idx]['metadata']
        return {
            'has_waveform': metadata.get('annotation_has_waveform'),
            'start_ms': float(metadata['annotation_start_ms']) if 'annotation_start_ms' in metadata else None,
            'end_ms': float(metadata['annotation_end_ms']) if 'annotation_end_ms' in metadata else None
        }
    
    def set_annotation(self, idx, has_waveform=None, start_ms=None, end_ms=None):
        """Set annotation in recording metadata"""
        # Save to history before making changes
        self.save_to_history()
        
        metadata = self.recordings[idx]['metadata']
        
        if has_waveform is not None:
            metadata['annotation_has_waveform'] = str(has_waveform)
        if start_ms is not None:
            metadata['annotation_start_ms'] = str(start_ms)
        if end_ms is not None:
            metadata['annotation_end_ms'] = str(end_ms)
        
        metadata['annotation_last_modified'] = datetime.now().isoformat()
        
        # Save to file immediately
        self.save_to_file()
    
    def save_to_file(self):
        """Save all recordings back to the original file"""
        output_lines = []
        
        for recording in self.recordings:
            # Write metadata
            for key, value in recording['metadata'].items():
                output_lines.append(f'"{key}","{value}"\n')
            
            # Write wave data
            for wave_idx, wave_val in recording['wave']:
                output_lines.append(f'"Wave",{wave_idx},{wave_val}\n')
        
        # Write to file
        with open(self.filepath, 'w') as f:
            f.writelines(output_lines)
        
        print(f"Saved to {self.filepath}")
    
    def save_to_history(self):
        """Save current state to history for undo/redo"""
        # Remove any history after current position
        self.history = self.history[:self.history_position + 1]
        
        # Deep copy recordings
        import copy
        self.history.append(copy.deepcopy(self.recordings))
        self.history_position += 1
        
        # Limit history size
        if len(self.history) > 50:
            self.history.pop(0)
            self.history_position -= 1
    
    def undo(self):
        """Undo last change"""
        if self.history_position > 0:
            self.history_position -= 1
            import copy
            self.recordings = copy.deepcopy(self.history[self.history_position])
            self.save_to_file()
            self.update_plot()
            print("Undo successful")
        else:
            print("Nothing to undo")
    
    def redo(self):
        """Redo last undone change"""
        if self.history_position < len(self.history) - 1:
            self.history_position += 1
            import copy
            self.recordings = copy.deepcopy(self.history[self.history_position])
            self.save_to_file()
            self.update_plot()
            print("Redo successful")
        else:
            print("Nothing to redo")
    
    def setup_plot(self):
        """Setup the matplotlib figure and widgets"""
        self.fig = plt.figure(figsize=(16, 10))
        
        # Disable default 's' key binding for save
        self.fig.canvas.mpl_disconnect(self.fig.canvas.manager.key_press_handler_id)
        
        # Main plot - more space at bottom for buttons
        self.ax = plt.subplot2grid((6, 4), (0, 0), colspan=4, rowspan=4)
        self.ax.set_position([0.08, 0.18, 0.88, 0.76])  # [left, bottom, width, height] - more bottom space
        
        # Buttons - moved down further
        button_y = 0.08
        button_height = 0.05
        button_width = 0.08
        
        # Navigation buttons
        ax_prev = plt.axes([0.02, button_y, button_width, button_height])
        ax_next = plt.axes([0.11, button_y, button_width, button_height])
        ax_jump = plt.axes([0.20, button_y, button_width, button_height])
        ax_jump_unann = plt.axes([0.29, button_y, button_width*1.3, button_height])
        
        self.btn_prev = Button(ax_prev, 'Previous (A)')
        self.btn_next = Button(ax_next, 'Next (D)')
        self.btn_jump = Button(ax_jump, 'Jump to...')
        self.btn_jump_unann = Button(ax_jump_unann, 'Next Unann. (U)')
        
        self.btn_prev.on_clicked(lambda x: self.prev_recording())
        self.btn_next.on_clicked(lambda x: self.next_recording())
        self.btn_jump.on_clicked(lambda x: self.jump_to_recording())
        self.btn_jump_unann.on_clicked(lambda x: self.jump_to_unannotated())
        
        # Quality buttons
        ax_yes = plt.axes([0.46, button_y, button_width, button_height])
        ax_no = plt.axes([0.55, button_y, button_width, button_height])
        
        self.btn_yes = Button(ax_yes, 'Has MEP (Y)', color='lightgreen')
        self.btn_no = Button(ax_no, 'No MEP (N)', color='lightcoral')
        
        self.btn_yes = Button(ax_yes, 'Has MEP (Y)', color='lightgreen')
        self.btn_no = Button(ax_no, 'No MEP (N)', color='lightcoral')
        
        self.btn_yes.on_clicked(lambda x: self.mark_has_waveform(True))
        self.btn_no.on_clicked(lambda x: self.mark_has_waveform(False))
        
        # Marking buttons
        ax_start = plt.axes([0.70, button_y, button_width, button_height])
        ax_end = plt.axes([0.79, button_y, button_width, button_height])
        ax_clear = plt.axes([0.88, button_y, button_width*0.7, button_height])
        
        self.btn_start = Button(ax_start, 'Start (S/M)', color='lightblue')
        self.btn_end = Button(ax_end, 'End (E)', color='lightblue')
        self.btn_clear = Button(ax_clear, 'Clear (C)', color='lightyellow')
        
        self.btn_start.on_clicked(lambda x: self.start_marking('start'))
        self.btn_end.on_clicked(lambda x: self.start_marking('end'))
        self.btn_clear.on_clicked(lambda x: self.clear_marks())
        
        # Undo/Redo buttons
        ax_undo = plt.axes([0.93, button_y, 0.03, button_height])
        ax_redo = plt.axes([0.97, button_y, 0.03, button_height])
        
        self.btn_undo = Button(ax_undo, 'Undo')
        self.btn_redo = Button(ax_redo, 'Redo')
        
        self.btn_undo.on_clicked(lambda x: self.undo())
        self.btn_redo.on_clicked(lambda x: self.redo())
        
        # Info text - at very top, full width of plot
        self.info_text = self.fig.text(0.5, 0.98, '', fontsize=9, verticalalignment='top',
                                       horizontalalignment='center', family='monospace')
        
        # Connect keyboard and mouse events
        self.fig.canvas.mpl_connect('key_press_event', self.on_key_press)
        self.fig.canvas.mpl_connect('button_press_event', self.on_mouse_click)
        self.fig.canvas.mpl_connect('button_release_event', self.on_mouse_release)
        self.fig.canvas.mpl_connect('motion_notify_event', self.on_mouse_move)
        
        # Lines for markers
        self.start_line = None
        self.end_line = None
        self.preview_line = None
        
        # Dragging state
        self.dragging = None  # None, 'start', or 'end'
        self.drag_threshold = 5  # pixels
        
        plt.show(block=False)
    
    def update_plot(self):
        """Update the plot with current recording"""
        if not self.recordings:
            return
            
        self.ax.clear()
        
        # Get current recording
        recording = self.recordings[self.current_idx]
        indices = np.array([w[0] for w in recording['wave']])
        values = np.array([w[1] for w in recording['wave']])
        time_ms = indices * 0.1  # 10kHz sampling
        
        # Get current annotation to check if rejected
        ann = self.get_annotation(self.current_idx)
        
        # Set background color for rejected waveforms
        if ann['has_waveform'] == 'False':
            self.ax.set_facecolor('#FFE5E5')  # Very light red
        else:
            self.ax.set_facecolor('white')
        
        # Plot the waveform
        self.ax.plot(time_ms, values, 'b-', linewidth=1.5)
        self.ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5, alpha=0.5)
        self.ax.axvline(x=0, color='k', linestyle='--', linewidth=1, alpha=0.5, label='Stimulus')
        
        # Get current annotation
        ann = self.get_annotation(self.current_idx)
        
        # Plot existing markers if they exist (make them draggable)
        if ann['start_ms'] is not None:
            self.start_line = self.ax.axvline(x=ann['start_ms'], color='green', 
                                             linestyle='--', linewidth=3, label='Start',
                                             picker=True, pickradius=5)
        if ann['end_ms'] is not None:
            self.end_line = self.ax.axvline(x=ann['end_ms'], color='red', 
                                           linestyle='--', linewidth=3, label='End',
                                           picker=True, pickradius=5)
        
        # Formatting
        self.ax.set_xlabel('Time (ms)', fontsize=12)  # Removed labelpad, using better spacing instead
        self.ax.set_ylabel('Amplitude (µV)', fontsize=12)
        self.ax.grid(True, alpha=0.3)
        self.ax.legend()
        
        # Update info text - single compact row
        filename = os.path.basename(self.filepath)
        total_annotated = sum(1 for rec in self.recordings 
                            if rec['metadata'].get('annotation_has_waveform') is not None)
        
        # Build single-line status
        parts = [f"File: {filename}", 
                 f"Recording: {self.current_idx + 1}/{len(self.recordings)}", 
                 f"Progress: {total_annotated}/{len(self.recordings)}"]
        
        if ann['has_waveform'] == 'True':
            parts.append("✓ HAS MEP")
        elif ann['has_waveform'] == 'False':
            parts.append("✗ NO MEP")
        else:
            parts.append("Not Annotated")
        
        if ann['start_ms'] is not None:
            parts.append(f"Start: {ann['start_ms']:.1f}ms")
        if ann['end_ms'] is not None:
            parts.append(f"End: {ann['end_ms']:.1f}ms")
        if ann['start_ms'] is not None and ann['end_ms'] is not None:
            duration = ann['end_ms'] - ann['start_ms']
            parts.append(f"Dur: {duration:.1f}ms")
        
        if self.marking_mode == 'start':
            parts.append(">>> MARK START <<<")
        elif self.marking_mode == 'end':
            parts.append(">>> MARK END <<<")
        
        info = "  |  ".join(parts)
        self.info_text.set_text(info)
        
        # Update title
        wave_comment = recording['metadata'].get('Wave comment', 'Unknown')
        timestamp = recording['metadata'].get('Date & time 0', 'Unknown')
        self.ax.set_title(f"{wave_comment} - {timestamp}", fontsize=14, fontweight='bold')
        
        self.fig.canvas.draw()
    
    def prev_recording(self):
        """Go to previous recording"""
        if self.current_idx > 0:
            self.current_idx -= 1
            self.marking_mode = None
            self.update_plot()
    
    def next_recording(self):
        """Go to next recording"""
        if self.current_idx < len(self.recordings) - 1:
            self.current_idx += 1
            self.marking_mode = None
            self.update_plot()
    
    def jump_to_recording(self):
        """Jump to specific recording number"""
        from tkinter import simpledialog
        rec_num = simpledialog.askinteger("Jump to Recording", 
                                         f"Enter recording number (1-{len(self.recordings)}):",
                                         minvalue=1, maxvalue=len(self.recordings),
                                         parent=self.master)
        if rec_num:
            self.current_idx = rec_num - 1
            self.marking_mode = None
            self.update_plot()
    
    def jump_to_unannotated(self):
        """Jump to next unannotated recording"""
        # Search forward from NEXT position (not current)
        for i in range(self.current_idx + 1, len(self.recordings)):
            ann = self.recordings[i]['metadata'].get('annotation_has_waveform')
            if ann is None:  # Completely unannotated
                self.current_idx = i
                self.marking_mode = None
                self.update_plot()
                print(f"Jumped to recording {i + 1} (unannotated)")
                return
        
        # If not found forward, search from beginning to current
        for i in range(0, self.current_idx):
            ann = self.recordings[i]['metadata'].get('annotation_has_waveform')
            if ann is None:  # Completely unannotated
                self.current_idx = i
                self.marking_mode = None
                self.update_plot()
                print(f"Jumped to recording {i + 1} (unannotated)")
                return
        
        # Check if current recording is unannotated (edge case - started on unannotated)
        current_ann = self.recordings[self.current_idx]['metadata'].get('annotation_has_waveform')
        if current_ann is None:
            print(f"Already on unannotated recording {self.current_idx + 1}")
            return
        
        # All annotated
        messagebox.showinfo("All Annotated", "All recordings have been annotated!")
        print("All recordings annotated")
    
    def mark_has_waveform(self, has_waveform):
        """Mark whether current recording has a waveform"""
        self.set_annotation(self.current_idx, has_waveform=has_waveform)
        print(f"Marked as {'HAS' if has_waveform else 'NO'} waveform")
        
        # If marking as YES, automatically start marking workflow
        if has_waveform:
            self.marking_mode = 'start'
            print("Click to mark START point")
        
        self.update_plot()
    
    def start_marking(self, mode):
        """Enter marking mode for start or end"""
        self.marking_mode = mode
        print(f"Click on plot to mark {mode} point (ESC to cancel)")
        self.update_plot()
    
    def clear_marks(self):
        """Clear start and end markers"""
        self.recordings[self.current_idx]['metadata'].pop('annotation_start_ms', None)
        self.recordings[self.current_idx]['metadata'].pop('annotation_end_ms', None)
        self.save_to_history()
        self.save_to_file()
        print("Markers cleared")
        self.update_plot()
    
    def on_mouse_move(self, event):
        """Handle mouse movement for preview line and dragging"""
        if event.inaxes != self.ax:
            # Remove preview line if mouse leaves plot
            if self.preview_line:
                self.preview_line.remove()
                self.preview_line = None
                self.fig.canvas.draw_idle()
            return
        
        time_ms = event.xdata
        if time_ms is None:
            return
        
        # If dragging, update the line position
        if self.dragging:
            if self.dragging == 'start' and self.start_line:
                self.start_line.set_xdata([time_ms, time_ms])
                self.fig.canvas.draw_idle()
            elif self.dragging == 'end' and self.end_line:
                self.end_line.set_xdata([time_ms, time_ms])
                self.fig.canvas.draw_idle()
        
        # If in marking mode, show preview line
        elif self.marking_mode:
            # Remove old preview line
            if self.preview_line:
                self.preview_line.remove()
            
            # Draw new preview line
            color = 'green' if self.marking_mode == 'start' else 'red'
            self.preview_line = self.ax.axvline(x=time_ms, color=color, 
                                               linestyle=':', linewidth=1, alpha=0.5)
            self.fig.canvas.draw_idle()
    
    def on_mouse_click(self, event):
        """Handle mouse clicks on the plot"""
        if event.inaxes != self.ax:
            return
        
        time_ms = event.xdata
        if time_ms is None:
            return
        
        # Check if clicking on existing line to start dragging
        if not self.marking_mode:
            ann = self.get_annotation(self.current_idx)
            
            # Check if near start line
            if ann['start_ms'] is not None and abs(time_ms - ann['start_ms']) < 2:
                self.dragging = 'start'
                return
            
            # Check if near end line
            if ann['end_ms'] is not None and abs(time_ms - ann['end_ms']) < 2:
                self.dragging = 'end'
                return
        
        # Otherwise, handle marking mode
        if self.marking_mode:
            # Remove preview line
            if self.preview_line:
                self.preview_line.remove()
                self.preview_line = None
            
            if self.marking_mode == 'start':
                self.set_annotation(self.current_idx, start_ms=time_ms)
                print(f"Start marked at {time_ms:.2f}ms")
                # Automatically move to marking end
                self.marking_mode = 'end'
                print("Now click to mark END point")
                self.update_plot()
                return
                
            elif self.marking_mode == 'end':
                self.set_annotation(self.current_idx, end_ms=time_ms)
                print(f"End marked at {time_ms:.2f}ms")
                # Complete the workflow
                self.marking_mode = None
                print("Annotation complete!")
            
            self.update_plot()
    
    def on_mouse_release(self, event):
        """Handle mouse release to finish dragging"""
        if self.dragging and event.inaxes == self.ax:
            time_ms = event.xdata
            if time_ms is not None:
                # Save the new position
                if self.dragging == 'start':
                    self.set_annotation(self.current_idx, start_ms=time_ms)
                    print(f"Start moved to {time_ms:.2f}ms")
                elif self.dragging == 'end':
                    self.set_annotation(self.current_idx, end_ms=time_ms)
                    print(f"End moved to {time_ms:.2f}ms")
                
                self.update_plot()
        
        self.dragging = None
    
    def on_key_press(self, event):
        """Handle keyboard shortcuts"""
        # Block matplotlib's default save shortcuts
        if event.key in ['s', 'ctrl+s']:
            # But allow 's' for manual start marking
            if not self.marking_mode or self.marking_mode != 'start':
                self.start_marking('start')
            return
            
        if event.key == 'a' or event.key == 'left':
            self.prev_recording()
        elif event.key == 'd' or event.key == 'right':
            self.next_recording()
        elif event.key == 'y':
            self.mark_has_waveform(True)
        elif event.key == 'n':
            self.mark_has_waveform(False)
        elif event.key == 'm':
            self.start_marking('start')
        elif event.key == 'e':
            self.start_marking('end')
        elif event.key == 'c':
            self.clear_marks()
        elif event.key == 'u':
            self.jump_to_unannotated()
        elif event.key == 'escape':
            self.marking_mode = None
            print("Marking mode cancelled")
            self.update_plot()
        elif event.key == 'ctrl+z':
            self.undo()
        elif event.key == 'ctrl+y' or event.key == 'ctrl+shift+z':
            self.redo()
        elif event.key == 'j':
            self.jump_to_recording()

# ============================================================================
# Main Execution with Standalone GUI
# ============================================================================

def main():
    """Main function to run the annotator"""
    root = tk.Tk()
    root.title("MEP Waveform Annotator")
    root.geometry("200x100")
    
    # Create annotator
    annotator = MEPAnnotator(master=root)
    
    # Add welcome message
    welcome = tk.Label(root, text="MEP Waveform Annotator\n\nUse File > Open File to begin", 
                      pady=20)
    welcome.pack()
    
    # Start the GUI
    root.mainloop()

if __name__ == "__main__":
    main()
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Interactive MEP Waveform Annotator
Allows manual annotation of MEP latency start/end points with quality ratings
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
import os
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox

class MEPAnnotator:
    def __init__(self, filepath):
        self.filepath = filepath
        
        # Parse the file
        self.recordings = self.parse_file(filepath)
        self.current_idx = 0
        
        # History for undo/redo
        self.history = []
        self.history_position = -1
        
        # Save initial state to history
        self.save_to_history()
        
        # Annotation state
        self.marking_mode = None  # None, 'start', or 'end'
        
        # Setup the plot
        self.setup_plot()
        self.update_plot()
    
    def parse_file(self, filepath):
        """Parse MEP file and return all recordings with line numbers"""
        recordings = []
        
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        current_metadata = {}
        current_wave = []
        current_start_line = 0
        in_wave_section = False
        
        for line_num, line in enumerate(lines):
            line_text = line.strip()
            if not line_text:
                continue
                
            parts = line_text.split(',')
            if len(parts) >= 2:
                key = parts[0].strip('"')
                value = parts[1].strip('"')
                
                if key == "Wave":
                    in_wave_section = True
                    wave_index = int(value)
                    wave_value = float(parts[2]) if len(parts) > 2 else 0
                    current_wave.append((wave_index, wave_value))
                else:
                    if in_wave_section and current_wave:
                        recordings.append({
                            'metadata': current_metadata.copy(),
                            'wave': current_wave.copy(),
                            'start_line': current_start_line
                        })
                        current_metadata = {}
                        current_wave = []
                        in_wave_section = False
                        current_start_line = line_num
                    
                    current_metadata[key] = value
        
        if current_wave:
            recordings.append({
                'metadata': current_metadata.copy(),
                'wave': current_wave.copy(),
                'start_line': current_start_line
            })
        
        return recordings
    
    def get_annotation(self, idx):
        """Get annotation from recording metadata"""
        metadata = self.recordings[idx]['metadata']
        return {
            'has_waveform': metadata.get('annotation_has_waveform'),
            'start_ms': float(metadata['annotation_start_ms']) if 'annotation_start_ms' in metadata else None,
            'end_ms': float(metadata['annotation_end_ms']) if 'annotation_end_ms' in metadata else None
        }
    
    def set_annotation(self, idx, has_waveform=None, start_ms=None, end_ms=None):
        """Set annotation in recording metadata"""
        # Save to history before making changes
        self.save_to_history()
        
        metadata = self.recordings[idx]['metadata']
        
        if has_waveform is not None:
            metadata['annotation_has_waveform'] = str(has_waveform)
        if start_ms is not None:
            metadata['annotation_start_ms'] = str(start_ms)
        if end_ms is not None:
            metadata['annotation_end_ms'] = str(end_ms)
        
        metadata['annotation_last_modified'] = datetime.now().isoformat()
        
        # Save to file immediately
        self.save_to_file()
    
    def save_to_file(self):
        """Save all recordings back to the original file"""
        output_lines = []
        
        for recording in self.recordings:
            # Write metadata
            for key, value in recording['metadata'].items():
                output_lines.append(f'"{key}","{value}"\n')
            
            # Write wave data
            for wave_idx, wave_val in recording['wave']:
                output_lines.append(f'"Wave",{wave_idx},{wave_val}\n')
        
        # Write to file
        with open(self.filepath, 'w') as f:
            f.writelines(output_lines)
        
        print(f"Saved to {self.filepath}")
    
    def save_to_history(self):
        """Save current state to history for undo/redo"""
        # Remove any history after current position
        self.history = self.history[:self.history_position + 1]
        
        # Deep copy recordings
        import copy
        self.history.append(copy.deepcopy(self.recordings))
        self.history_position += 1
        
        # Limit history size
        if len(self.history) > 50:
            self.history.pop(0)
            self.history_position -= 1
    
    def undo(self):
        """Undo last change"""
        if self.history_position > 0:
            self.history_position -= 1
            import copy
            self.recordings = copy.deepcopy(self.history[self.history_position])
            self.save_to_file()
            self.update_plot()
            print("Undo successful")
        else:
            print("Nothing to undo")
    
    def redo(self):
        """Redo last undone change"""
        if self.history_position < len(self.history) - 1:
            self.history_position += 1
            import copy
            self.recordings = copy.deepcopy(self.history[self.history_position])
            self.save_to_file()
            self.update_plot()
            print("Redo successful")
        else:
            print("Nothing to redo")
    
    def setup_plot(self):
        """Setup the matplotlib figure and widgets"""
        self.fig = plt.figure(figsize=(16, 10))
        
        # Main plot
        self.ax = plt.subplot2grid((6, 4), (0, 0), colspan=4, rowspan=4)
        
        # Buttons
        button_y = 0.02
        button_height = 0.05
        button_width = 0.08
        
        # Navigation buttons
        ax_prev = plt.axes([0.02, button_y, button_width, button_height])
        ax_next = plt.axes([0.11, button_y, button_width, button_height])
        ax_jump = plt.axes([0.20, button_y, button_width, button_height])
        
        self.btn_prev = Button(ax_prev, 'Previous (A)')
        self.btn_next = Button(ax_next, 'Next (D)')
        self.btn_jump = Button(ax_jump, 'Jump to...')
        
        self.btn_prev.on_clicked(lambda x: self.prev_recording())
        self.btn_next.on_clicked(lambda x: self.next_recording())
        self.btn_jump.on_clicked(lambda x: self.jump_to_recording())
        
        # Quality buttons
        ax_yes = plt.axes([0.35, button_y, button_width, button_height])
        ax_no = plt.axes([0.44, button_y, button_width, button_height])
        
        self.btn_yes = Button(ax_yes, 'Has MEP (Y)', color='lightgreen')
        self.btn_no = Button(ax_no, 'No MEP (N)', color='lightcoral')
        
        self.btn_yes.on_clicked(lambda x: self.mark_has_waveform(True))
        self.btn_no.on_clicked(lambda x: self.mark_has_waveform(False))
        
        # Marking buttons
        ax_start = plt.axes([0.59, button_y, button_width, button_height])
        ax_end = plt.axes([0.68, button_y, button_width, button_height])
        ax_clear = plt.axes([0.77, button_y, button_width, button_height])
        
        self.btn_start = Button(ax_start, 'Mark Start (S)', color='lightblue')
        self.btn_end = Button(ax_end, 'Mark End (E)', color='lightblue')
        self.btn_clear = Button(ax_clear, 'Clear (C)', color='lightyellow')
        
        self.btn_start.on_clicked(lambda x: self.start_marking('start'))
        self.btn_end.on_clicked(lambda x: self.start_marking('end'))
        self.btn_clear.on_clicked(lambda x: self.clear_marks())
        
        # Undo/Redo buttons
        ax_undo = plt.axes([0.88, button_y, 0.05, button_height])
        ax_redo = plt.axes([0.94, button_y, 0.05, button_height])
        
        self.btn_undo = Button(ax_undo, 'Undo')
        self.btn_redo = Button(ax_redo, 'Redo')
        
        self.btn_undo.on_clicked(lambda x: self.undo())
        self.btn_redo.on_clicked(lambda x: self.redo())
        
        # Info text
        self.info_text = self.fig.text(0.02, 0.92, '', fontsize=12, verticalalignment='top')
        
        # Connect keyboard and mouse events
        self.fig.canvas.mpl_connect('key_press_event', self.on_key_press)
        self.fig.canvas.mpl_connect('button_press_event', self.on_mouse_click)
        
        # Lines for markers
        self.start_line = None
        self.end_line = None
    
    def update_plot(self):
        """Update the plot with current recording"""
        self.ax.clear()
        
        # Get current recording
        recording = self.recordings[self.current_idx]
        indices = np.array([w[0] for w in recording['wave']])
        values = np.array([w[1] for w in recording['wave']])
        time_ms = indices * 0.1  # 10kHz sampling
        
        # Plot the waveform
        self.ax.plot(time_ms, values, 'b-', linewidth=1.5)
        self.ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5, alpha=0.5)
        self.ax.axvline(x=0, color='k', linestyle='--', linewidth=1, alpha=0.5, label='Stimulus')
        
        # Get current annotation
        ann = self.get_annotation(self.current_idx)
        
        # Plot existing markers if they exist
        if ann['start_ms'] is not None:
            self.start_line = self.ax.axvline(x=ann['start_ms'], color='green', 
                                             linestyle='--', linewidth=2, label='Start')
        if ann['end_ms'] is not None:
            self.end_line = self.ax.axvline(x=ann['end_ms'], color='red', 
                                           linestyle='--', linewidth=2, label='End')
        
        # Formatting
        self.ax.set_xlabel('Time (ms)', fontsize=12)
        self.ax.set_ylabel('Amplitude (µV)', fontsize=12)
        self.ax.grid(True, alpha=0.3)
        self.ax.legend()
        
        # Update info text
        waveform_status = "Unknown"
        if ann['has_waveform'] == 'True':
            waveform_status = "YES - Has MEP"
        elif ann['has_waveform'] == 'False':
            waveform_status = "NO - No MEP"
        
        marker_status = ""
        if ann['start_ms'] is not None and ann['end_ms'] is not None:
            duration = ann['end_ms'] - ann['start_ms']
            marker_status = f"\nStart: {ann['start_ms']:.1f}ms | End: {ann['end_ms']:.1f}ms | Duration: {duration:.1f}ms"
        elif ann['start_ms'] is not None:
            marker_status = f"\nStart: {ann['start_ms']:.1f}ms | End: Not set"
        elif ann['end_ms'] is not None:
            marker_status = f"\nStart: Not set | End: {ann['end_ms']:.1f}ms"
        
        filename = os.path.basename(self.filepath)
        total_annotated = sum(1 for rec in self.recordings 
                            if rec['metadata'].get('annotation_has_waveform') is not None)
        
        info = (f"File: {filename}\n"
                f"Recording: {self.current_idx + 1} / {len(self.recordings)}\n"
                f"Status: {waveform_status}{marker_status}\n"
                f"Progress: {total_annotated} / {len(self.recordings)} annotated\n"
                f"Mode: {self.marking_mode if self.marking_mode else 'Navigation'}")
        
        self.info_text.set_text(info)
        
        # Update title
        wave_comment = recording['metadata'].get('Wave comment', 'Unknown')
        timestamp = recording['metadata'].get('Date & time 0', 'Unknown')
        self.ax.set_title(f"{wave_comment} - {timestamp}", fontsize=14, fontweight='bold')
        
        plt.draw()
    
    def prev_recording(self):
        """Go to previous recording"""
        if self.current_idx > 0:
            self.current_idx -= 1
            self.marking_mode = None
            self.update_plot()
    
    def next_recording(self):
        """Go to next recording"""
        if self.current_idx < len(self.recordings) - 1:
            self.current_idx += 1
            self.marking_mode = None
            self.update_plot()
    
    def jump_to_recording(self):
        """Jump to specific recording number"""
        root = tk.Tk()
        root.withdraw()
        
        rec_num = tk.simpledialog.askinteger("Jump to Recording", 
                                            f"Enter recording number (1-{len(self.recordings)}):",
                                            minvalue=1, maxvalue=len(self.recordings))
        if rec_num:
            self.current_idx = rec_num - 1
            self.marking_mode = None
            self.update_plot()
        
        root.destroy()
    
    def mark_has_waveform(self, has_waveform):
        """Mark whether current recording has a waveform"""
        self.set_annotation(self.current_idx, has_waveform=has_waveform)
        print(f"Marked as {'HAS' if has_waveform else 'NO'} waveform")
        self.update_plot()
    
    def start_marking(self, mode):
        """Enter marking mode for start or end"""
        self.marking_mode = mode
        print(f"Click on plot to mark {mode} point (ESC to cancel)")
        self.update_plot()
    
    def clear_marks(self):
        """Clear start and end markers"""
        self.recordings[self.current_idx]['metadata'].pop('annotation_start_ms', None)
        self.recordings[self.current_idx]['metadata'].pop('annotation_end_ms', None)
        self.save_to_history()
        self.save_to_file()
        print("Markers cleared")
        self.update_plot()
    
    def on_mouse_click(self, event):
        """Handle mouse clicks on the plot"""
        if event.inaxes == self.ax and self.marking_mode:
            time_ms = event.xdata
            
            if self.marking_mode == 'start':
                self.set_annotation(self.current_idx, start_ms=time_ms)
                print(f"Start marked at {time_ms:.2f}ms")
            elif self.marking_mode == 'end':
                self.set_annotation(self.current_idx, end_ms=time_ms)
                print(f"End marked at {time_ms:.2f}ms")
            
            self.marking_mode = None
            self.update_plot()
    
    def on_key_press(self, event):
        """Handle keyboard shortcuts"""
        if event.key == 'a' or event.key == 'left':
            self.prev_recording()
        elif event.key == 'd' or event.key == 'right':
            self.next_recording()
        elif event.key == 'y':
            self.mark_has_waveform(True)
        elif event.key == 'n':
            self.mark_has_waveform(False)
        elif event.key == 's':
            self.start_marking('start')
        elif event.key == 'e':
            self.start_marking('end')
        elif event.key == 'c':
            self.clear_marks()
        elif event.key == 'escape':
            self.marking_mode = None
            print("Marking mode cancelled")
            self.update_plot()
        elif event.key == 'ctrl+z':
            self.undo()
        elif event.key == 'ctrl+y' or event.key == 'ctrl+shift+z':
            self.redo()
        elif event.key == 'j':
            self.jump_to_recording()
    
    def run(self):
        """Start the annotation interface"""
        print("="*70)
        print("MEP WAVEFORM ANNOTATOR")
        print("="*70)
        print("\nKeyboard Shortcuts:")
        print("  A / Left Arrow  - Previous recording")
        print("  D / Right Arrow - Next recording")
        print("  Y - Mark as HAS waveform")
        print("  N - Mark as NO waveform")
        print("  S - Mark start point (then click on plot)")
        print("  E - Mark end point (then click on plot)")
        print("  C - Clear markers")
        print("  J - Jump to recording number")
        print("  Ctrl+Z - Undo")
        print("  Ctrl+Y - Redo")
        print("  ESC - Cancel marking mode")
        print("="*70)
        print(f"\nLoaded {len(self.recordings)} recordings from {os.path.basename(self.filepath)}")
        
        plt.show()

# ============================================================================
# Main Execution with GUI File Selector
# ============================================================================

def select_file():
    """Open file dialog to select MEP file"""
    root = tk.Tk()
    root.withdraw()
    
    filepath = filedialog.askopenfilename(
        title="Select MEP File",
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        initialdir=os.path.expanduser("~")
    )
    
    root.destroy()
    return filepath

if __name__ == "__main__":
    import sys
    import tkinter.simpledialog
    
    # Check if file provided as argument
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        # Open file dialog
        filepath = select_file()
    
    if not filepath or not os.path.exists(filepath):
        print("No file selected or file not found. Exiting.")
        sys.exit(1)
    
    try:
        annotator = MEPAnnotator(filepath)
        annotator.run()
    except Exception as e:
        messagebox.showerror("Error", f"Failed to load file:\n{str(e)}")
        raise
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Interactive MEP Waveform Annotator
Allows manual annotation of MEP latency start/end points with quality ratings
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
import json
import os
from datetime import datetime

class MEPAnnotator:
    def __init__(self, filepath):
        self.filepath = filepath
        self.annotations_file = filepath.replace('.txt', '_annotations.json')
        
        # Parse the file
        self.recordings = self.parse_file(filepath)
        self.current_idx = 0
        
        # Load existing annotations
        self.annotations = self.load_annotations()
        
        # History for undo/redo
        self.history = []
        self.history_position = -1
        
        # Annotation state
        self.marking_mode = None  # None, 'start', or 'end'
        self.temp_start = None
        self.temp_end = None
        
        # Setup the plot
        self.setup_plot()
        self.update_plot()
        
    def parse_file(self, filepath):
        """Parse MEP file and return all recordings"""
        recordings = []
        
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        current_metadata = {}
        current_wave = []
        in_wave_section = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            parts = line.split(',')
            if len(parts) >= 2:
                key = parts[0].strip('"')
                value = parts[1].strip('"')
                
                if key == "Wave":
                    in_wave_section = True
                    wave_index = int(value)
                    wave_value = float(parts[2]) if len(parts) > 2 else 0
                    current_wave.append((wave_index, wave_value))
                else:
                    if in_wave_section and current_wave:
                        recordings.append({
                            'metadata': current_metadata.copy(),
                            'wave': current_wave.copy()
                        })
                        current_metadata = {}
                        current_wave = []
                        in_wave_section = False
                    
                    current_metadata[key] = value
        
        if current_wave:
            recordings.append({
                'metadata': current_metadata.copy(),
                'wave': current_wave.copy()
            })
        
        return recordings
    
    def load_annotations(self):
        """Load existing annotations from JSON file"""
        if os.path.exists(self.annotations_file):
            with open(self.annotations_file, 'r') as f:
                return json.load(f)
        return {}
    
    def save_annotations(self):
        """Save annotations to JSON file"""
        with open(self.annotations_file, 'w') as f:
            json.dump(self.annotations, f, indent=2)
        print(f"Annotations saved to {self.annotations_file}")
    
    def get_annotation(self, idx):
        """Get annotation for recording index"""
        key = str(idx)
        if key in self.annotations:
            return self.annotations[key]
        return {'has_waveform': None, 'start_ms': None, 'end_ms': None}
    
    def set_annotation(self, idx, has_waveform=None, start_ms=None, end_ms=None):
        """Set annotation for recording index"""
        key = str(idx)
        
        # Save to history before making changes
        self.save_to_history()
        
        if key not in self.annotations:
            self.annotations[key] = {}
        
        if has_waveform is not None:
            self.annotations[key]['has_waveform'] = has_waveform
        if start_ms is not None:
            self.annotations[key]['start_ms'] = start_ms
        if end_ms is not None:
            self.annotations[key]['end_ms'] = end_ms
        
        self.annotations[key]['last_modified'] = datetime.now().isoformat()
        self.save_annotations()
    
    def save_to_history(self):
        """Save current state to history for undo/redo"""
        # Remove any history after current position
        self.history = self.history[:self.history_position + 1]
        
        # Save current annotations
        self.history.append(json.dumps(self.annotations))
        self.history_position += 1
        
        # Limit history size
        if len(self.history) > 50:
            self.history.pop(0)
            self.history_position -= 1
    
    def undo(self):
        """Undo last change"""
        if self.history_position > 0:
            self.history_position -= 1
            self.annotations = json.loads(self.history[self.history_position])
            self.save_annotations()
            self.update_plot()
            print("Undo successful")
        else:
            print("Nothing to undo")
    
    def redo(self):
        """Redo last undone change"""
        if self.history_position < len(self.history) - 1:
            self.history_position += 1
            self.annotations = json.loads(self.history[self.history_position])
            self.save_annotations()
            self.update_plot()
            print("Redo successful")
        else:
            print("Nothing to redo")
    
    def setup_plot(self):
        """Setup the matplotlib figure and widgets"""
        self.fig = plt.figure(figsize=(16, 10))
        
        # Main plot
        self.ax = plt.subplot2grid((6, 4), (0, 0), colspan=4, rowspan=4)
        
        # Buttons
        button_y = 0.02
        button_height = 0.05
        button_width = 0.08
        
        # Navigation buttons
        ax_prev = plt.axes([0.02, button_y, button_width, button_height])
        ax_next = plt.axes([0.11, button_y, button_width, button_height])
        ax_jump = plt.axes([0.20, button_y, button_width, button_height])
        
        self.btn_prev = Button(ax_prev, 'Previous (A)')
        self.btn_next = Button(ax_next, 'Next (D)')
        self.btn_jump = Button(ax_jump, 'Jump to...')
        
        self.btn_prev.on_clicked(lambda x: self.prev_recording())
        self.btn_next.on_clicked(lambda x: self.next_recording())
        self.btn_jump.on_clicked(lambda x: self.jump_to_recording())
        
        # Quality buttons
        ax_yes = plt.axes([0.35, button_y, button_width, button_height])
        ax_no = plt.axes([0.44, button_y, button_width, button_height])
        
        self.btn_yes = Button(ax_yes, 'Has MEP (Y)', color='lightgreen')
        self.btn_no = Button(ax_no, 'No MEP (N)', color='lightcoral')
        
        self.btn_yes.on_clicked(lambda x: self.mark_has_waveform(True))
        self.btn_no.on_clicked(lambda x: self.mark_has_waveform(False))
        
        # Marking buttons
        ax_start = plt.axes([0.59, button_y, button_width, button_height])
        ax_end = plt.axes([0.68, button_y, button_width, button_height])
        ax_clear = plt.axes([0.77, button_y, button_width, button_height])
        
        self.btn_start = Button(ax_start, 'Mark Start (S)', color='lightblue')
        self.btn_end = Button(ax_end, 'Mark End (E)', color='lightblue')
        self.btn_clear = Button(ax_clear, 'Clear (C)', color='lightyellow')
        
        self.btn_start.on_clicked(lambda x: self.start_marking('start'))
        self.btn_end.on_clicked(lambda x: self.start_marking('end'))
        self.btn_clear.on_clicked(lambda x: self.clear_marks())
        
        # Undo/Redo buttons
        ax_undo = plt.axes([0.88, button_y, 0.05, button_height])
        ax_redo = plt.axes([0.94, button_y, 0.05, button_height])
        
        self.btn_undo = Button(ax_undo, 'Undo')
        self.btn_redo = Button(ax_redo, 'Redo')
        
        self.btn_undo.on_clicked(lambda x: self.undo())
        self.btn_redo.on_clicked(lambda x: self.redo())
        
        # Info text
        self.info_text = self.fig.text(0.02, 0.92, '', fontsize=12, verticalalignment='top')
        
        # Connect keyboard and mouse events
        self.fig.canvas.mpl_connect('key_press_event', self.on_key_press)
        self.fig.canvas.mpl_connect('button_press_event', self.on_mouse_click)
        
        # Lines for markers
        self.start_line = None
        self.end_line = None
    
    def update_plot(self):
        """Update the plot with current recording"""
        self.ax.clear()
        
        # Get current recording
        recording = self.recordings[self.current_idx]
        indices = np.array([w[0] for w in recording['wave']])
        values = np.array([w[1] for w in recording['wave']])
        time_ms = indices * 0.1  # 10kHz sampling
        
        # Plot the waveform
        self.ax.plot(time_ms, values, 'b-', linewidth=1.5)
        self.ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5, alpha=0.5)
        self.ax.axvline(x=0, color='k', linestyle='--', linewidth=1, alpha=0.5, label='Stimulus')
        
        # Get current annotation
        ann = self.get_annotation(self.current_idx)
        
        # Plot existing markers if they exist
        if ann['start_ms'] is not None:
            self.start_line = self.ax.axvline(x=ann['start_ms'], color='green', 
                                             linestyle='--', linewidth=2, label='Start')
        if ann['end_ms'] is not None:
            self.end_line = self.ax.axvline(x=ann['end_ms'], color='red', 
                                           linestyle='--', linewidth=2, label='End')
        
        # Formatting
        self.ax.set_xlabel('Time (ms)', fontsize=12)
        self.ax.set_ylabel('Amplitude (µV)', fontsize=12)
        self.ax.grid(True, alpha=0.3)
        self.ax.legend()
        
        # Update info text
        waveform_status = "Unknown"
        if ann['has_waveform'] is True:
            waveform_status = "YES - Has MEP"
        elif ann['has_waveform'] is False:
            waveform_status = "NO - No MEP"
        
        marker_status = ""
        if ann['start_ms'] is not None and ann['end_ms'] is not None:
            duration = ann['end_ms'] - ann['start_ms']
            marker_status = f"\nStart: {ann['start_ms']:.1f}ms | End: {ann['end_ms']:.1f}ms | Duration: {duration:.1f}ms"
        elif ann['start_ms'] is not None:
            marker_status = f"\nStart: {ann['start_ms']:.1f}ms | End: Not set"
        elif ann['end_ms'] is not None:
            marker_status = f"\nStart: Not set | End: {ann['end_ms']:.1f}ms"
        
        filename = os.path.basename(self.filepath)
        total_annotated = sum(1 for a in self.annotations.values() if a.get('has_waveform') is not None)
        
        info = (f"File: {filename}\n"
                f"Recording: {self.current_idx + 1} / {len(self.recordings)}\n"
                f"Status: {waveform_status}{marker_status}\n"
                f"Progress: {total_annotated} / {len(self.recordings)} annotated\n"
                f"Mode: {self.marking_mode if self.marking_mode else 'Navigation'}")
        
        self.info_text.set_text(info)
        
        # Update title
        wave_comment = recording['metadata'].get('Wave comment', 'Unknown')
        timestamp = recording['metadata'].get('Date & time 0', 'Unknown')
        self.ax.set_title(f"{wave_comment} - {timestamp}", fontsize=14, fontweight='bold')
        
        plt.draw()
    
    def prev_recording(self):
        """Go to previous recording"""
        if self.current_idx > 0:
            self.current_idx -= 1
            self.marking_mode = None
            self.update_plot()
    
    def next_recording(self):
        """Go to next recording"""
        if self.current_idx < len(self.recordings) - 1:
            self.current_idx += 1
            self.marking_mode = None
            self.update_plot()
    
    def jump_to_recording(self):
        """Jump to specific recording number"""
        try:
            rec_num = int(input(f"Enter recording number (1-{len(self.recordings)}): "))
            if 1 <= rec_num <= len(self.recordings):
                self.current_idx = rec_num - 1
                self.marking_mode = None
                self.update_plot()
            else:
                print(f"Invalid recording number. Must be between 1 and {len(self.recordings)}")
        except ValueError:
            print("Invalid input. Please enter a number.")
    
    def mark_has_waveform(self, has_waveform):
        """Mark whether current recording has a waveform"""
        self.set_annotation(self.current_idx, has_waveform=has_waveform)
        print(f"Marked as {'HAS' if has_waveform else 'NO'} waveform")
        self.update_plot()
    
    def start_marking(self, mode):
        """Enter marking mode for start or end"""
        self.marking_mode = mode
        print(f"Click on plot to mark {mode} point (ESC to cancel)")
        self.update_plot()
    
    def clear_marks(self):
        """Clear start and end markers"""
        self.set_annotation(self.current_idx, start_ms=None, end_ms=None)
        print("Markers cleared")
        self.update_plot()
    
    def on_mouse_click(self, event):
        """Handle mouse clicks on the plot"""
        if event.inaxes == self.ax and self.marking_mode:
            time_ms = event.xdata
            
            if self.marking_mode == 'start':
                self.set_annotation(self.current_idx, start_ms=time_ms)
                print(f"Start marked at {time_ms:.2f}ms")
            elif self.marking_mode == 'end':
                self.set_annotation(self.current_idx, end_ms=time_ms)
                print(f"End marked at {time_ms:.2f}ms")
            
            self.marking_mode = None
            self.update_plot()
    
    def on_key_press(self, event):
        """Handle keyboard shortcuts"""
        if event.key == 'a' or event.key == 'left':
            self.prev_recording()
        elif event.key == 'd' or event.key == 'right':
            self.next_recording()
        elif event.key == 'y':
            self.mark_has_waveform(True)
        elif event.key == 'n':
            self.mark_has_waveform(False)
        elif event.key == 's':
            self.start_marking('start')
        elif event.key == 'e':
            self.start_marking('end')
        elif event.key == 'c':
            self.clear_marks()
        elif event.key == 'escape':
            self.marking_mode = None
            print("Marking mode cancelled")
            self.update_plot()
        elif event.key == 'ctrl+z':
            self.undo()
        elif event.key == 'ctrl+y' or event.key == 'ctrl+shift+z':
            self.redo()
        elif event.key == 'j':
            self.jump_to_recording()
    
    def run(self):
        """Start the annotation interface"""
        print("="*70)
        print("MEP WAVEFORM ANNOTATOR")
        print("="*70)
        print("\nKeyboard Shortcuts:")
        print("  A / Left Arrow  - Previous recording")
        print("  D / Right Arrow - Next recording")
        print("  Y - Mark as HAS waveform")
        print("  N - Mark as NO waveform")
        print("  S - Mark start point (then click on plot)")
        print("  E - Mark end point (then click on plot)")
        print("  C - Clear markers")
        print("  J - Jump to recording number")
        print("  Ctrl+Z - Undo")
        print("  Ctrl+Y - Redo")
        print("  ESC - Cancel marking mode")
        print("="*70)
        print(f"\nLoaded {len(self.recordings)} recordings from {os.path.basename(self.filepath)}")
        
        if os.path.exists(self.annotations_file):
            print(f"Loaded existing annotations from {os.path.basename(self.annotations_file)}")
        
        plt.show()

# ============================================================================
# Main Execution
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        # Example usage
        filepath = "/path/to/your/mep/file.txt"
        print("Usage: python mep_annotator.py <path_to_mep_file.txt>")
        print(f"Using example path: {filepath}")
    
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    
    annotator = MEPAnnotator(filepath)
    annotator.run()