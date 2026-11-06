#════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════#
#This code was written by Aysan Hemmatiortakand. Last updated 11/17/2025 
#you can contact me for any additional questions or information via Email 
#email address :aysanhemmatiortakand@gmail.com
#github = https://github.com/Aysikal
#════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════#

import tkinter as tk
from tkinter import simpledialog, messagebox
import sys
import numpy as np
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from astropy.time import Time
from astropy.coordinates import SkyCoord, AltAz, EarthLocation
import astropy.units as u
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from ancillary_functions import airmass_function, get_fli, calculate_sky_magnitude

# -------------------------------------------------------------------
# INO configuration
# -------------------------------------------------------------------
SITE_NAME      = "INO"
SITE_LAT, SITE_LON, SITE_ELEV = 35.674, 51.3188, 3600
SITE_LOCATION  = EarthLocation(lat=SITE_LAT*u.deg,
                               lon=SITE_LON*u.deg,
                               height=SITE_ELEV*u.m)
LOCAL_TIMEZONE   = "Asia/Tehran"

# -------------------------
# Main Window Setup
# -------------------------
root = tk.Tk()
root.title("Calculator")
root.geometry("400x250")
root.configure(bg='#F0F0F0')
custom_font = ('Helvetica', 12)

# -------------------------
# Variables
# -------------------------
mode = 'High'
year = month = day = hour = minute = None
RA = DEC = filter_choice = None
magnitude = None
binning = None
seeing_conditions = None
#non_linearity_error = 3500 # ADU
#over_exposure_error = 4000 # ADU 
pixel_scale = 0.101 
h = 6.62620e-34
c = 2.9979250e8
readnoise = 3.7  # electrons
D = 3.4
d = 0.6
S = np.pi*(D/2)**2 - np.pi*(d/2)**2  # effective mirror surface (m^2)

# Gain (ADU -> electrons)
GAIN = 1  

# Filters, Bandwidths, Extinction1
CW = {'u': 3540e-10, 'g': 4770e-10, 'r': 6230e-10, 'i': 7630e-10}        # central wavelength in meters
band_width = {'u': 600e-10, 'g': 1380e-10, 'r': 1380e-10, 'i': 1520e-10} # effective bandwidth in meters
extinction = {'u': 0.404, 'g': 0.35, 'r': 0.2, 'i': 0.15}  

# System Efficiency ( 2.3 * 10**(-2) for i, ? for red)
E = 2.3 * 10**(-2)

# -------------------------
# GUI & Input functions
# -------------------------
class BaseDialog(simpledialog.Dialog):
    def __init__(self, parent, title=None, message=None, prompt=None, options=None, initialvalue='', input_type='string'):
        self.message = message
        self.prompt = prompt
        self.options = options
        self.initialvalue = initialvalue
        self.input_type = input_type
        self.result = None
        super().__init__(parent, title=title)

    def body(self, master):
        master.configure(bg='#FFFFFF')
        if self.message:
            tk.Label(master, text=self.message, font=custom_font, bg='#FFFFFF').pack(pady=10, padx=10)
        if self.prompt and self.options:
            self.var = tk.StringVar(value=self.options[0])
            tk.Label(master, text=self.prompt, font=custom_font, bg='#FFFFFF').pack(pady=10)
            for option in self.options:
                tk.Radiobutton(master, text=option, variable=self.var, value=option, font=custom_font,
                               bg='#FFFFFF', anchor='w').pack(pady=2, padx=20, anchor='w')
            return None
        if self.prompt:
            tk.Label(master, text=self.prompt, font=custom_font, bg='#FFFFFF').pack(pady=10)
            self.entry = tk.Entry(master, font=custom_font)
            self.entry.insert(0, self.initialvalue)
            self.entry.pack(pady=5, padx=10)
            return self.entry

    def buttonbox(self):
        box = tk.Frame(self, bg='#FFFFFF')
        tk.Button(box, text="OK", width=10, command=self.ok, font=custom_font,
                  bg='#4CAF50', fg='white', activebackground='#45A049').pack(side='left', padx=5, pady=5)
        tk.Button(box, text="Cancel", width=10, command=self.cancel, font=custom_font,
                  bg='#F44336', fg='white', activebackground='#E53935').pack(side='right', padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        box.pack()

    def apply(self):
        if self.prompt and self.options:
            self.result = self.var.get()
        elif self.prompt:
            self.result = self.entry.get()

    def ok(self, event=None):
        self.apply()
        self.destroy()

    def cancel(self, event=None):
        self.result = None
        self.destroy()

def ask_input(title, message=None, prompt=None, options=None, initialvalue='', input_type='string'):
    dialog = BaseDialog(root, title=title, message=message, prompt=prompt,
                        options=options, initialvalue=initialvalue, input_type=input_type)
    if dialog.result is None:
        sys.exit()
    if input_type == 'float':
        try:
            return float(dialog.result)
        except ValueError:
            messagebox.showerror("Error", "Invalid input, please enter a valid number.")
            return ask_input(title, message, prompt, options, initialvalue, input_type)
    elif input_type == 'int':
        try:
            return int(dialog.result)
        except ValueError:
            messagebox.showerror("Error", "Invalid input, please enter a valid integer.")
            return ask_input(title, message, prompt, options, initialvalue, input_type)
    return dialog.result.strip()

def ask_object_inputs():
    global RA, DEC, filter_choice, magnitude
    messagebox.showinfo("Object Inputs", "Please enter the object details.")
    RA = ask_input("RA Input", prompt="Enter RA (HH:MM:SS):")
    DEC = ask_input("DEC Input", prompt="Enter DEC (DD:MM:SS):")
    filter_options = ["u", "g", "r", "i", "z"]
    filter_choice = ask_input("Filter Selection", prompt="Choose a filter:", options=filter_options)
    magnitude = ask_input("Magnitude Input", prompt="Enter magnitude:", input_type='float')

def ask_system_inputs():
    global binning, seeing_conditions, seeing
    binning_choice = ask_input("Binning Selection", prompt="Choose binning (1x1 or 2x2):", options=["1", "2"])
    binning = int(binning_choice)
    seeing_options = ["optimal (0.6 - 0.8 arcseconds)", "minimal (0.8 - 1 arcseconds)",
                      "moderate (1 - 1.3 arcseconds)", "high (1.3 - 1.5 arcseconds)",
                      "very high (1.5 - 2 arcseconds)"]
    seeing_dict = {"optimal (0.6 - 0.8 arcseconds)": 0.7,
                   "minimal (0.8 - 1 arcseconds)": 0.9,
                   "moderate (1 - 1.3 arcseconds)": 1.15,
                   "high (1.3 - 1.5 arcseconds)": 1.4,
                   "very high (1.5 - 2 arcseconds)": 1.75}
    seeing_conditions = ask_input("Seeing Conditions", prompt="Choose seeing conditions:", options=seeing_options)
    seeing = seeing_dict[seeing_conditions]

def ask_date_time():
    global year, month, day, hour, minute
    messagebox.showinfo("Attention", "Time and date entries MUST be local (Tehran time)")
    year = ask_input("Date and Time", prompt="Enter the year (YYYY):", input_type='int')
    month = ask_input("Date and Time", prompt="Enter the month (1-12):", input_type='int')
    day = ask_input("Date and Time", prompt="Enter the day (1-31):", input_type='int')
    hour = ask_input("Date and Time", prompt="Enter the hour (0-23):", input_type='int')
    minute = ask_input("Date and Time", prompt="Enter the minute (0-59):", input_type='int')

# -------------------------
# Photon -> Electron Conversion Helper
# -------------------------
def photons_to_electrons(photons_per_sec, efficiency):
    return photons_per_sec * efficiency *GAIN

# -------------------------
# SNR Calculations with Dark Noise & Time Ranges
# -------------------------
def calculate_snr(year, month, day, hour, minute, RA, DEC, seeing, pixel_scale, binning, h, c, CW, filter_choice,
                  magnitude, extinction, band_width, exposure_time, E, S, calculate_sky_magnitude, readnoise):

    # Enforce exposure_time limits
    if exposure_time < 30 or exposure_time > 320:
        raise ValueError("Exposure time must be between 30s and 320s.")

    # Define dark noise STDs and SNR multipliers for ranges
    if 30 <= exposure_time < 90:
        DARK_STD = 4.3117
        SNR_MULT = 1.0
    elif 90 <= exposure_time < 150:
        DARK_STD = 4.7820
        SNR_MULT = 1.2
    elif 150 <= exposure_time < 210:
        DARK_STD = 5.2813
        SNR_MULT = 1.35
    elif 210 <= exposure_time <= 320:
        DARK_STD = 8.5406
        SNR_MULT = 1.52

    date_str = f"{year}-{month:02d}-{day:02d}"
    airmass = airmass_function(date_str, hour, minute, RA, DEC)
    npix = np.pi * ((seeing / pixel_scale*2*binning)** 2)
    wav_m = CW[filter_choice]
    bw_m = band_width[filter_choice]

    # Source flux
    m_corrected = magnitude + (airmass * extinction[filter_choice]) # Correct for extinction
    f_nu_erg = 10 ** (-0.4 * (m_corrected + 48.6)) # get star f_nu from mag, AB magnitude 
    f_nu_J = f_nu_erg * 1e-7 # get star f_nu in Jouls
    f_lambda_J_per_m = f_nu_J * c / (wav_m ** 2) # get f_lambda in lambda (multiply by c/lambda^2, lambda is central wavelength in meters)
    power_per_cm2 = f_lambda_J_per_m * bw_m # power (multiply by bandwidth in meters)
    total_power_J_per_s = power_per_cm2 * (S * 1e4)  # multiply by effective mirror surface in cm^2
    E_photon = h * c / wav_m # energy of a photon with wav_m = central wavelength 
    photons_per_s = total_power_J_per_s / E_photon # number of photons per sec
    electrons_per_s = photons_to_electrons(photons_per_s, E) # where efficiecy is taken into account

    # Signal electrons
    signal_e = electrons_per_s * exposure_time #The SNR numinator, electrons purly coming from the star.

    # Sky background
    sky_mag = calculate_sky_magnitude(date_str, hour, minute, RA, DEC) # takes the LOCAL time you input -> turns into UTC. RIGHT NOW, it is calibrated for i and r
    f_nu_s_erg = 10 ** (-0.4 * (sky_mag + 48.6)) # get sky f_nu from magget sky f_nu from mag
    f_nu_s_J = f_nu_s_erg * 1e-7 # get sky f_nu in Jouls
    f_lambda_s_J_per_m = f_nu_s_J * c / (wav_m ** 2) # get sky f_lambds (multiply by c/lambda^2, lambda is central wavelength in meters)
    power_sky_per_cm2 = f_lambda_s_J_per_m * bw_m # power (multiply by bandwidth in meters)
    total_sky_power_J_per_s = power_sky_per_cm2 * (S * 1e4)
    photons_sky_per_s = total_sky_power_J_per_s / E_photon  # number of photons per sec
    electrons_sky_per_s = photons_to_electrons(photons_sky_per_s, E)
    C_e_per_sec_per_pix = electrons_sky_per_s * (pixel_scale ** 2) # sky_e per second per pixel
    N_sky_e_per_pix = C_e_per_sec_per_pix * exposure_time  #sky_e per pixel

    # Net signal and noise including dark noise
    noise = np.sqrt(signal_e + (npix * N_sky_e_per_pix) + npix*((readnoise)**2 + (DARK_STD**2)))
    SNR = signal_e / noise

    # Apply SNR multiplier for range
    SNR *= SNR_MULT

    return SNR

# -------------------------
# User Interaction
# -------------------------
def snr_calculator():
    global mode
    mode = 'snr'
    root.withdraw()
    ask_date_time()
    ask_object_inputs()
    ask_system_inputs()
    messagebox.showinfo("Attention", "Exposure time should be in seconds")
    while True:
        exposure_time = ask_input("SNR Calculator", prompt="Enter exposure time (seconds):", input_type='float')
        if exposure_time < 30 or exposure_time > 320:
            messagebox.showerror("Invalid Time", "Exposure time must be between 30s and 320s.")
            continue
        if messagebox.askyesno("Confirm Exposure Time", f"Entered Exposure Time:\n{exposure_time} seconds\n\nIs this correct?"):
            process_snr_calculation(exposure_time)
            break

def process_snr_calculation(exposure_time):
    snr = calculate_snr(year, month, day, hour, minute, RA, DEC, seeing, pixel_scale, binning,
                        h, c, CW, filter_choice, magnitude, extinction, band_width,
                        exposure_time, E, S, calculate_sky_magnitude, readnoise)
    message = f"Calculated SNR: {snr:.2f}"
    print(message)
    messagebox.showinfo("SNR Calculation Result", message)
    sys.exit()

# -------------------------
# GUI Buttons
# -------------------------
button_style = {'font': custom_font, 'bg': '#008CBA', 'fg': 'white',
                'activebackground': '#007BA7', 'activeforeground': 'white',
                'width': 30, 'bd': 0, 'cursor': 'hand2'}

tk.Button(root, text="SNR Calculator", command=snr_calculator, **button_style).pack(pady=15)

root.mainloop()
