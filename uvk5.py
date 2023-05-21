# Quansheng UV-K5 driver (c) 2023 Jacek Lipkowski <sq5bpf@lipkowski.org>
#
# based on template.py Copyright 2012 Dan Smith <dsmith@danplanet.com>
#
#
# This is a preliminary version of a driver for the UV-K5
# It is based on my reverse engineering effort described here:
# https://github.com/sq5bpf/uvk5-reverse-engineering
#
# Warning: this driver is experimental, it may brick your radio,
# eat your lunch and mess up your configuration. Before even attempting
# to use it save a memory image from the radio using k5prog:
# https://github.com/sq5bpf/k5prog
#
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import struct
import logging
import serial  
import logging
from chirp import chirp_common, directory, bitwise, memmap, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
        RadioSettingValueBoolean, RadioSettingValueList, \
        RadioSettingValueInteger, RadioSettingValueString, \
        RadioSettingValueFloat, RadioSettingValueMap, RadioSettings

LOG = logging.getLogger(__name__)

DRIVER_VERSION="Quansheng UV-K5 driver v20230512 (c) Jacek Lipkowski SQ5BPF"
PRINT_CONSOLE=False

MEM_FORMAT = """
#seekto 0x0000;
struct {
  ul32 freq;
  ul32 offset;
  u8 rxcode;
  u8 txcode;
  u8 code_flag;
  u8 flags1;
  u8 flags2;
  u8 dtmf_flags;
  u8 step;
  u8 scrambler;
} channel[214];

#seekto 0x640;
ul16 fmfreq[20];

#seekto 0xe70;
u8 call_channel;
u8 squelch;
u8 max_talk_time;
u8 noaa_autoscan;
u8 unknown1;
u8 unknown2;
u8 vox_level;
u8 mic_gain;
u8 unknown3;
u8 channel_display_mode;
u8 crossband;
u8 battery_save;
u8 dual_watch;
u8 tail_note_elimination;
u8 vfo_open;

#seekto 0xe90;
u8 beep_control;
#seekto 0xe95;
u8 scan_resume_mode;
u8 auto_keypad_lock;
u8 power_on_dispmode;
u8 password[4];

#seekto 0xea0;
u8 keypad_tone;
u8 language;

#seekto 0xea8;
u8 alarm_mode;
u8 reminding_of_end_talk;
u8 repeater_tail_elimination;

#seekto 0xeb0;
char logo_line1[16];
char logo_line2[16];

#seekto 0xf40;
u8 int_flock;
u8 int_350tx;
u8 int_unknown1;
u8 int_200tx;
u8 int_500tx;
u8 int_350en;
u8 int_screen;

#seekto 0xf50;
struct {
char name[16];
} channelname[200];

"""
#flags1
FLAGS1_OFFSET=0b1
FLAGS1_ISSCANLIST=0b100
FLAGS1_ISAM=0b10000

#flags2
FLAGS2_BCLO=0b10000
FLAGS2_POWER_MASK=0b1100
FLAGS2_POWER_HIGH=0b1000
FLAGS2_POWER_MEDIUM=0b0100
FLAGS2_POWER_LOW=0b0000
FLAGS2_BANDWIDTH=0b10
FLAGS2_REVERSE=0b1

#dtmf_flags
PTTID_LIST = ["off", "BOT", "EOT", "BOTH"]
FLAGS_DTMF_PTTID_MASK=0b110 # PTTID: 00 - disabled, 01 - BOT, 10 - EOT, 11 - BOTH
FLAGS_DTMF_PTTID_DISABLED=0b000
FLAGS_DTMF_PTTID_BOT=0b010
FLAGS_DTMF_PTTID_EOT=0b100
FLAGS_DTMF_PTTID_BOTH=0b110
FLAGS_DTMF_DECODE=0b1

#scrambler
SCRAMBLER_LIST = [ "off", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10" ]

#channel display mode
CHANNELDISP_LIST = [ "Frequency", "Channel No", "Channel Name" ]
#battery save
BATSAVE_LIST = [ "OFF", "1:1", "1:2", "1:3", "1:4" ]

#Crossband receiving/transmitting
CROSSBAND_LIST = [ "Off", "Band A", "Band B" ]
DUALWATCH_LIST= CROSSBAND_LIST

#steps
STEPS = [ 2.5, 5.0, 6.25, 10.0, 12.5, 25.0 , 8.33 ]

#ctcss/dcs codes
TMODES = ["", "Tone", "DTCS", "DTCS"]
TONE_NONE=0
TONE_CTCSS=1
TONE_DCS=2
TONE_RDCS=3

#DTCS_CODES = sorted(chirp_common.DTCS_CODES)
CTCSS_TONES = [
        67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4,
        88.5, 91.5, 94.8, 97.4, 100.0, 103.5, 107.2, 110.9,
        114.8, 118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2,
        151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
        177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5,
        203.5, 206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8,
        250.3, 254.1
        ]

#       from ft4.py
DTCS_CODES = [ 
              23,  25,  26,  31,  32,  36,  43,  47,  51,  53,  54,
              65,  71,  72,  73,  74,  114, 115, 116, 122, 125, 131,
              132, 134, 143, 145, 152, 155, 156, 162, 165, 172, 174,
              205, 212, 223, 225, 226, 243, 244, 245, 246, 251, 252,
              255, 261, 263, 265, 266, 271, 274, 306, 311, 315, 325,
              331, 332, 343, 346, 351, 356, 364, 365, 371, 411, 412,
              413, 423, 431, 432, 445, 446, 452, 454, 455, 462, 464,
              465, 466, 503, 506, 516, 523, 526, 532, 546, 565, 606,
              612, 624, 627, 631, 632, 654, 662, 664, 703, 712, 723,
              731, 732, 734, 743, 754
              ]

FLOCK_LIST=[ "Off", "FCC", "CE", "GB", "430", "438" ]
SCANRESUME_LIST = [ "TO: Resume after 5 seconds", "CO: Resume after signal dissapears", "SE: Stop scanning after receiving a signal" ]
WELCOME_LIST = [ "Full Screen", "Welcome Info", "Voltage" ]
KEYPADTONE_LIST = [ "Off", "Chinese", "English" ]
LANGUAGE_LIST = [ "Chinese", "English" ]
ALARMMODE_LIST = [ "SITE", "TONE" ]
REMENDOFTALK_LIST = [ "Off" , "ROGER", "MDC" ]
RTE_LIST = [ "Off" , "100ms", "200ms", "300ms", "400ms", "500ms", "600ms", "700ms", "800ms", "900ms" ]

MEM_SIZE=0x2000 #size of all memory
PROG_SIZE=0x1d00 #size of the memowy that we will program
MEM_BLOCK=0x80 #largest block of memory that we can reliably write

# the communication is obfuscated using this fine mechanism
def xorarr(data: bytes):
    tbl=[ 22, 108, 20, 230, 46, 145, 13, 64, 33, 53, 213, 64, 19, 3, 233, 128]
    #x=[]
    x=b""
    r=0
    for byte in data:
        x+=bytes([byte^tbl[r]])
        r=(r+1)%len(tbl)
    return x

# if this crc was used for communication to AND from the radio, then it
# would be a measure to increase reliability.
# but it's only used towards the radio, so it's for further obfuscation
def calculate_crc16_xmodem(data: bytes):
    poly=0x1021
    crc = 0x0
    for byte in data:
        crc = crc ^ (byte << 8)
        for i in range(8):
            crc = crc << 1
            if (crc & 0x10000):
                crc = (crc ^ poly ) & 0xFFFF
    return crc & 0xFFFF


def _send_command(radio,data: bytes):
    """Send a command to UV-K5 radio"""
    serial=radio.pipe
    serial.timeout=0.5

    crc=calculate_crc16_xmodem(data)
    data2=data+bytes([crc&0xff,(crc>>8)&0xff])

    command=b"\xAB\xCD"+bytes([len(data)])+b"\x00"+xorarr(data2)+b"\xDC\xBA"
#    print("Sending command: %s" % util.hexprint(command))
    serial.write(command)

def _receive_reply(radio):
    serial=radio.pipe
    serial.timeout=0.5
    headed: bytes
    cmd: bytes
    footer: bytes

    header=serial.read(4)
    if header[0]!=0xAB or header[1]!=0xCD or header[3]!=0x00:
        if PRINT_CONSOLE:
            print("bad response header")
        raise errors.RadioError( "Bad response header")
 
        return False

    cmd=serial.read(int(header[2]))
    footer=serial.read(4)

    if footer[2]!=0xDC or footer[3]!=0xBA:
        if PRINT_CONSOLE:
            print("bad response footer")
        raise errors.RadioError( "Bad response footer")

        return False

    cmd2=xorarr(cmd)
    
    if PRINT_CONSOLE:
        print("Received reply: %s" % util.hexprint(cmd2))

    return cmd2


def _getstring(data: bytes, begin, maxlen):
    s=""
    c=0
    for i in data:
        c+=1
        if c<begin:
            continue
        if i<ord(' ') or i>ord('~'):
            break
        s+=chr(i)
    return s


def _sayhello(radio):
    hellopacket=b"\x14\x05\x04\x00\x6a\x39\x57\x64"

    tries=5
    while (True):
        _send_command(radio,hellopacket)
        o=_receive_reply(radio)
        #print("hello",o)
        if (o) :
            break
        tries-=1
        if tries==0:
            print("Failed to initialize radio")
            return False
    firmware=_getstring(o,5,16)
    if PRINT_CONSOLE:
        print("found firmware",firmware)
    radio.FIRMWARE_VERSION=firmware
    return True

def _readmem(radio,offset,len):
    readmem=b"\x1b\x05\x08\x00"+bytes([offset&0xff,(offset>>8)&0xff,len,0])+b"\x6a\x39\x57\x64"
    _send_command(radio,readmem)
    o=_receive_reply(radio)
    if PRINT_CONSOLE:
        print("readmem Received data: %s" % util.hexprint(o))
    return o[8:]


def _writemem(radio,data,offset):
    dlen=len(data)
    writemem=b"\x1d\x05"+bytes([dlen+8])+b"\x00"+bytes([offset&0xff,(offset>>8)&0xff,dlen,1])+b"\x6a\x39\x57\x64"+data
    _send_command(radio,writemem)
    o=_receive_reply(radio)
    if PRINT_CONSOLE:
        print("writemem Received data: %s" % util.hexprint(o))
    if o[0]==0x1e and o[1]==(offset&0xff) and o[2]==(offset>>8)&0xff:
        return True
    return False


def _resetradio(radio):
    resetpacket=b"\xdd\x05\x00\x00"
    _send_command(radio,resetpacket)

def warnfirmware(radio):
    if radio.FIRMWARE_VERSION!=radio.FIRMWARE_VERSION_PREV:
        raise errors.RadioError(
                "This is NOT an error.\n"
                "Found firmware "+radio.FIRMWARE_VERSION+"\n")
    radio.FIRMWARE_VERSION_PREV=radio.FIRMWARE_VERSION



def do_download(radio):
    """This is your download function"""
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE
    status.msg = "Downloading from radio"
    radio.status_fn(status)

    eeprom=b""
    _sayhello(radio)

    addr=0
    while addr<MEM_SIZE:
        o=_readmem(radio,addr,MEM_BLOCK)
        status.cur=addr
        radio.status_fn(status)

        if o and len(o)==MEM_BLOCK:
            eeprom+=o
            addr+=MEM_BLOCK
        else:
            return False
    #warnfirmware()
    return memmap.MemoryMapBytes(eeprom)



def do_upload(radio):
    """This is your upload function"""
    # NOTE: Remove this in your real implementation!
    #raise Exception("This template driver does not really work!")

    serial = radio.pipe

    status = chirp_common.Status()
    status.cur = 0
    status.max = PROG_SIZE
    status.msg = "Uploading to radio"
    radio.status_fn(status)

    _sayhello(radio)

    addr=0
    while addr<PROG_SIZE:
        o = radio.get_mmap()[addr:addr+MEM_BLOCK]
        _writemem(radio,o,addr)
        status.cur=addr
        radio.status_fn(status)
        if o:
            addr+=MEM_BLOCK
        else:
            return False
    status.msg = "Uploaded OK"

    _resetradio(radio)
    #warnfirmware()

    return True


# Uncomment this to actually register this radio in CHIRP
@directory.register
class TemplateRadio(chirp_common.CloneModeRadio):
    """Quansheng UV-K5"""
    VENDOR = "Quansheng"     # Replace this with your vendor
    MODEL = "UV-K5"  # Replace this with your model
    BAUD_RATE = 38400    # Replace this with your baud rate
    #DTCS_CODES = sorted(chirp_common.DTCS_CODES)

    # All new drivers should be "Byte Clean" so leave this in place.
    NEEDS_COMPAT_SERIAL = False
    FIRMWARE_VERSION_PREV=""
    FIRMWARE_VERSION=""

    def get_prompts(x=None):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This is an experimental driver for the Quanscheng UV-K5. '
             'It may harm your radio, or worse. Use at your own risk.\n\n'
             'Before attempting to do any changes please download'
             'the memory image from the radio with chirp or k5prog '
             'and keep it. This can be later used to recover the '
             'original settings. \n\n'
             'FM radio, DTMF settings and scanlists are not yet implemented' )
        rp.pre_download = _(
            "1. Turn radio on.\n"
            "2. Connect cable to mic/spkr connector.\n"
            "3. Make sure connector is firmly connected.\n"
            "4. Click OK to download image from device.\n\n"
            "It will may not work if you turn o the radio "
            "with the cable already attached\n")
        rp.pre_upload = _(
            "1. Turn radio on.\n"
            "2. Connect cable to mic/spkr connector.\n"
            "3. Make sure connector is firmly connected.\n"
            "4. Click OK to upload the image to device.\n\n"
            "It will may not work if you turn o the radio "
            "with the cable already attached")
        return rp

    # Return information about this radio's features, including
    # how many memories it has, what bands it supports, etc
    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.valid_dtcs_codes = DTCS_CODES
        #rf.valid_dtcs_codes = chirp_common.ALL_DTCS_CODES
        rf.has_rx_dtcs = True
        rf.has_ctone = True
        rf.has_settings = True
        rf.has_comment = True
        rf.valid_name_length = 16
        rf.valid_power_levels = [ "High", "Med", "Low" ]
        rf.valid_tuning_steps = [ 0.01, 0.1, 1.0 ] + STEPS #hack so we can input any frequency, the 0.1 and 0.01 steps don't work unfortunately

        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]

        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_modes = ["FM", "NFM", "AM" ]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "TSQL-R", "Cross"]
        rf.memory_bounds = (1, 214)  # This radio supports memories 0-9
#        rf.valid_bands = [(144000000, 148000000),  # Supports 2-meters
#                          (440000000, 450000000),  # Supports 70-centimeters
#                          ]
        rf.valid_bands = [(18000000,  620000000),  # For now everything that the BK4819 chip supports
                          (840000000, 1300000000)
                          ]
        return rf

    # Do a download of the radio from the serial port
    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    # Do an upload of the radio to the serial port
    def sync_out(self):
        do_upload(self)

    # Convert the raw byte array into a memory object structure
    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    # Return a raw representation of the memory object, which
    # is very helpful for development
    def get_raw_memory(self, number):
        return repr(self._memobj.channel[number-1])

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        #print("validate_memory mem:",mem.number," name:",mem.name," msg:",msgs)
        return msgs



    def _set_tone(self, mem, _mem):
        ((txmode, txtone, txpol),
         (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)

        if txmode == "Tone":
            txtoval = CTCSS_TONES.index(txtone)
            txmoval = 0b01
        elif txmode == "DTCS":
            txmoval = txpol == "R" and 0b11 or 0b10
            txtoval = DTCS_CODES.index(txtone)
        else:
            txmoval=0
            txtoval = 0

        if rxmode == "Tone":
            rxtoval = CTCSS_TONES.index(rxtone)
            rxmoval = 0b01
        elif rxmode == "DTCS":
            rxmoval = rxpol == "R" and 0b11 or 0b10
            rxtoval = DTCS_CODES.index(rxtone)
        else:
            rxmoval=0
            rxtoval = 0

        _mem.code_flag = ( _mem.code_flag & 0b11001100 ) | (txmoval << 4) | rxmoval
        #print("set_tone code_flag:"+hex(_mem.code_flag),"rxcode=",rxtoval,"txcode=",txtoval)
        _mem.rxcode=rxtoval
        _mem.txcode=txtoval


    def _get_tone(self, mem, _mem):
        rxtype=_mem.code_flag&0x03
        txtype=(_mem.code_flag>>4)&0x03
        rx_tmode = TMODES[rxtype]
        tx_tmode = TMODES[txtype]

        rx_tone = tx_tone = None

        if tx_tmode == "Tone":
            if _mem.txcode<len(CTCSS_TONES):
                tx_tone = CTCSS_TONES[_mem.txcode]
            else:
                tx_tone=0
                tx_tmode = ""
        elif tx_tmode == "DTCS":
            if _mem.txcode<len(DTCS_CODES):
                tx_tone = DTCS_CODES[_mem.txcode]
            else:
                tx_tone = 0
                tx_tmode = ""

        if rx_tmode == "Tone":
            if _mem.rxcode<len(CTCSS_TONES):
                rx_tone = CTCSS_TONES[_mem.rxcode]
            else:
                rx_tone=0
                rx_tmode = ""
        elif rx_tmode == "DTCS":
            if _mem.rxcode<len(DTCS_CODES):
                rx_tone = DTCS_CODES[_mem.rxcode]
            else:
                rx_tone = 0
                rx_tmode = ""


        tx_pol = txtype == 0x03 and "R" or "N"
        rx_pol = rxtype == 0x03 and "R" or "N"

        chirp_common.split_tone_decode(mem, (tx_tmode, tx_tone, tx_pol),
                                       (rx_tmode, rx_tone, rx_pol))



    # Extract a high-level memory object from the low-level memory map
    # This is called to populate a memory in the UI
    def get_memory(self, number2):
        number=number2-1

        # Get a low-level memory object mapped to the image
        _mem = self._memobj.channel[number]


        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        # Ugly hack: the extra parameters will be shown in the comments field, 
        # because there is no other way to show them without the user 
        # right-clicking every channel
        # Unfortunately this means that this field is read-only
        mem.comment="" 

        mem.number = number2                 # Set the memory number

        if number>199:
            mem.name="VFO_"+str(number-199)
        else:
            _mem2 = self._memobj.channelname[number]
            for char in _mem2.name:
                if str(char) == "\xFF" or str(char) == "\x00":
                    break
                mem.name += str(char)
            mem.name = mem.name.rstrip()

#            mem.name = str(_mem2.name).rstrip(chr(0xff)).rstrip()  # Set the alpha tag


        # Convert your low-level frequency to Hertz
        mem.freq = int(_mem.freq)*10
        mem.offset = int(_mem.offset)*10


        if (mem.offset==0):
            mem.duplex = ''
        else:
            if (_mem.flags1&FLAGS1_OFFSET):
                mem.duplex = '-'
            else:
                mem.duplex = '+'

        # tone data 
        self._get_tone(mem, _mem)

        # mode
        if (_mem.flags1 & FLAGS1_ISAM )>0 :
            mem.mode="AM"
        else:
            if (_mem.flags2 & FLAGS2_BANDWIDTH )>0:
                mem.mode="NFM"
            else:
                mem.mode="FM"

        # tuning step
        tstep=(_mem.step>>1)&0x7
        if tstep < len(STEPS):
            mem.tuning_step = STEPS[tstep]
        else:
            mem.tuning_step = 2.5


        # power
        if (_mem.flags2 & FLAGS2_POWER_MASK ) == FLAGS2_POWER_HIGH:
            mem.power="High"
        elif (_mem.flags2 & FLAGS2_POWER_MASK ) == FLAGS2_POWER_MEDIUM:
            mem.power="Med"
        else:
            mem.power="Low"

        # We'll consider any blank (i.e. 0MHz frequency) to be empty
        if (_mem.freq == 0xffffffff) or (_mem.freq == 0):
            mem.empty = True
        else:
            mem.empty = False

        mem.extra = RadioSettingGroup("Extra", "extra")
# BCLO
        is_bclo=bool(_mem.flags2&FLAGS2_BCLO>0);
        rs = RadioSetting("bclo", "BCLO", RadioSettingValueBoolean(is_bclo))
        mem.extra.append(rs)
        mem.comment+="BCLO:"+(is_bclo and "ON" or "off")+" "

# Frequency reverse
        is_frev=bool(_mem.flags2&FLAGS2_REVERSE>0);
        rs = RadioSetting("frev", "FreqRev", RadioSettingValueBoolean(is_frev))
        mem.extra.append(rs)
        mem.comment+="FreqReverse:"+(is_frev and "ON" or "off")+" "
#
# PTTID
        pttid=(_mem.dtmf_flags&FLAGS_DTMF_PTTID_MASK)>>1
        rs = RadioSetting("pttid", "PTTID", RadioSettingValueList(PTTID_LIST,PTTID_LIST[pttid]))
        mem.extra.append(rs)
        mem.comment+="PTTid:"+PTTID_LIST[pttid]+" "
# DTMF DECODE
        is_dtmf=bool(_mem.dtmf_flags&FLAGS_DTMF_DECODE>0);
        rs = RadioSetting("dtmfdecode", "DTMF decode", RadioSettingValueBoolean(is_dtmf))
        mem.extra.append(rs)
        mem.comment+="DTMFdecode:"+(is_dtmf and "ON" or "off")+" "
#
# Scrambler
        if _mem.scrambler&0x0f<len(SCRAMBLER_LIST):
            enc=_mem.scrambler&0x0f
        else:
            enc=0

        rs = RadioSetting("scrambler", "Scrambler", RadioSettingValueList(SCRAMBLER_LIST,SCRAMBLER_LIST[enc]))
        mem.extra.append(rs)
        mem.comment+="Scrambler:"+SCRAMBLER_LIST[enc]+" "

        return mem

    def set_settings(self, settings):
        _mem = self._memobj
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            #print("set_settings element",element.get_name()," value",element.value)

            # call channel
            if element.get_name()=="call_channel":
                _mem.call_channel=int(element.value)-1

            #squelch
            if element.get_name()=="squelch":
                _mem.squelch=int(element.value)
            #TOT
            if element.get_name()=="tot":
                _mem.max_talk_time=int(element.value)
            #NOAA autoscan
            if element.get_name()=="noaa_autoscan":
                _mem.noaa_autoscan=element.value and 1 or 0

            #vox level
            if element.get_name()=="vox_level":
                _mem.vox_level=int(element.value)-1

            #mic gain
            if element.get_name()=="mic_gain":
                _mem.mic_gain=int(element.value)

            #Channel display mode
            if element.get_name()=="channel_display_mode":
                _mem.channel_display_mode=CHANNELDISP_LIST.index(str(element.value))

            #Crossband receiving/transmitting
            if element.get_name()=="crossband":
                _mem.crossband=CROSSBAND_LIST.index(str(element.value))

            #Battery Save
            if element.get_name()=="battery_save":
                _mem.battery_save=BATSAVE_LIST.index(str(element.value))
            #Dual Watch
            if element.get_name()=="dualwatch":
                _mem.dual_watch=DUALWATCH_LIST.index(str(element.value))

            #Tail tone elimination
            if element.get_name()=="tail_note_elimination":
                _mem.tail_note_elimination=element.value and 1 or 0

            #VFO Open
            if element.get_name()=="vfo_open":
                _mem.vfo_open=element.value and 1 or 0

            #Beep control
            if element.get_name()=="beep_control":
                _mem.beep_control=element.value and 1 or 0

            #Scan resume mode
            if element.get_name()=="scan_resume_mode":
                _mem.scan_resume_mode=SCANRESUME_LIST.index(str(element.value))

            #Auto keypad lock
            if element.get_name()=="auto_keypad_lock":
                _mem.auto_keypad_lock=element.value and 1 or 0

            #Power on display mode
            if element.get_name()=="welcome_mode":
                _mem.power_on_dispmode=WELCOME_LIST.index(str(element.value))

            #Keypad Tone
            if element.get_name()=="keypad_tone":
                _mem.keypad_tone=KEYPADTONE_LIST.index(str(element.value))

            #Language
            if element.get_name()=="language":
                _mem.language=LANGUAGE_LIST.index(str(element.value))

            #Alarm mode
            if element.get_name()=="alarm_mode":
                _mem.alarm_mode=ALARMMODE_LIST.index(str(element.value))

            #Reminding of end of talk
            if element.get_name()=="reminding_of_end_talk":
                _mem.reminding_of_end_talk=REMENDOFTALK_LIST.index(str(element.value))

            #Repeater tail tone elimination
            if element.get_name()=="repeater_tail_elimination":
                _mem.repeater_tail_elimination=RTE_LIST.index(str(element.value))

            #Logo string 1
            if element.get_name()=="logo1":
                b=str(element.value).rstrip("\x20\xff\x00")+"\x00"*12
                _mem.logo_line1=b[0:12]+"\xff\xff\xff\xff"


            #Logo string 2
            if element.get_name()=="logo2":
                b=str(element.value).rstrip("\x20\xff\x00")+"\x00"*12
                _mem.logo_line2=b[0:12]+"\xff\xff\xff\xff"




### unlock settings
            #FLOCK
            if element.get_name()=="flock":
                _mem.int_flock=FLOCK_LIST.index(str(element.value))

#350TX
            if element.get_name()=="350tx":
                _mem.int_350tx=element.value and 1 or 0

#UNKNOWN1
            if element.get_name()=="unknown1":
                _mem.int_unknown1=element.value and 1 or 0


#200TX
            if element.get_name()=="200tx":
                _mem.int_200tx=element.value and 1 or 0


#500TX
            if element.get_name()=="500tx":
                _mem.int_500tx=element.value and 1 or 0


#350EN
            if element.get_name()=="350en":
                _mem.int_350en=element.value and 1 or 0






    def get_settings(self):
        #print ("get_settings")
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        unlock = RadioSettingGroup("unlock", "Unlock Settings")
        fmradio = RadioSettingGroup("fmradio", "FM Radio (unimplemented yet)")
        roinfo = RadioSettingGroup("roinfo","Information (read-only)")

        top = RadioSettings(basic, unlock, fmradio,roinfo)

    #basic settings

        # call channel
        tmpc=_mem.call_channel+1
        if tmpc>200:
            tmpc=1
        rs = RadioSetting("call_channel", "One key call channel",RadioSettingValueInteger(1, 200, tmpc))
        basic.append(rs)

        # squelch
        tmpsq=_mem.squelch
        if tmpsq>9:
            tmpsq=1
        rs = RadioSetting("squelch", "Squelch", RadioSettingValueInteger(0, 9, tmpsq))
        basic.append(rs)

        # TOT
        tmptot=_mem.max_talk_time
        if tmptot>10:
            tmptot=10
        rs = RadioSetting("tot", "Max talk time [min]", RadioSettingValueInteger(0, 10, tmptot))
        basic.append(rs)

        # NOAA autoscan
        rs = RadioSetting("noaa_autoscan", "NOAA Autoscan", RadioSettingValueBoolean(bool(_mem.noaa_autoscan>0)))
        basic.append(rs)

        # VOX Level
        tmpvox=_mem.vox_level+1
        if tmpvox>10:
            tmpvox=10
        rs = RadioSetting("vox_level", "VOX Level", RadioSettingValueInteger(1, 10, tmpvox))
        basic.append(rs)

        # Mic gain
        tmpmicgain=_mem.mic_gain
        if tmpmicgain>4:
            tmpmicgain=4
        rs = RadioSetting("mic_gain", "Mic Gain", RadioSettingValueInteger(0, 4, tmpmicgain))
        basic.append(rs)

        # Channel display mode
        tmpchdispmode=_mem.channel_display_mode
        if tmpchdispmode>=len(CHANNELDISP_LIST):
            tmpchdispmode=0
        rs = RadioSetting("channel_display_mode", "Channel display mode", RadioSettingValueList( CHANNELDISP_LIST, CHANNELDISP_LIST[tmpchdispmode]))
        basic.append(rs)

        #Crossband receiving/transmitting
        tmpcross=_mem.crossband
        if tmpcross>=len(CROSSBAND_LIST):
            tmpcross=0
        rs = RadioSetting("crossband", "Cross-band receiving/transmitting", RadioSettingValueList( CROSSBAND_LIST, CROSSBAND_LIST[tmpcross]))
        basic.append(rs)

        #Battery save
        rs = RadioSetting("battery_save", "Battery Save", RadioSettingValueList( BATSAVE_LIST, BATSAVE_LIST[_mem.battery_save]))
        basic.append(rs)

        #Dual watch
        tmpdual=_mem.dual_watch
        if tmpdual>=len(DUALWATCH_LIST):
            tmpdual=0
        rs = RadioSetting("dualwatch", "Dual Watch", RadioSettingValueList( DUALWATCH_LIST, DUALWATCH_LIST[tmpdual]))
        basic.append(rs)

        #Tail tone elimination
        rs = RadioSetting("tail_note_elimination", "Tail tone elimination", RadioSettingValueBoolean(bool(_mem.tail_note_elimination>0)))
        basic.append(rs)

        #VFO open
        rs = RadioSetting("vfo_open", "VFO open", RadioSettingValueBoolean(bool(_mem.vfo_open>0)))
        basic.append(rs)

        #Beep control
        rs = RadioSetting("beep_control", "Beep control", RadioSettingValueBoolean(bool(_mem.beep_control>0)))
        basic.append(rs)

        #Scan resume mode
        tmpscanres=_mem.scan_resume_mode
        if tmpscanres>=len(SCANRESUME_LIST):
            tmpscanres=0
        rs = RadioSetting("scan_resume_mode", "Scan resume mode", RadioSettingValueList( SCANRESUME_LIST, SCANRESUME_LIST[tmpscanres]))
        basic.append(rs)

        #Auto keypad lock
        rs = RadioSetting("auto_keypad_lock", "Auto keypad lock", RadioSettingValueBoolean(bool(_mem.auto_keypad_lock>0)))
        basic.append(rs)


        #Power on display mode
        tmpdispmode=_mem.power_on_dispmode
        if tmpdispmode>=len(WELCOME_LIST):
            tmpdispmode=0
        rs = RadioSetting("welcome_mode", "Power on display mode", RadioSettingValueList( WELCOME_LIST, WELCOME_LIST[tmpdispmode]))
        basic.append(rs)

        #Keypad Tone
        tmpkeypadtone=_mem.keypad_tone
        if tmpkeypadtone>=len(KEYPADTONE_LIST):
            tmpkeypadtone=0
        rs = RadioSetting("keypad_tone", "Keypad tone", RadioSettingValueList( KEYPADTONE_LIST, KEYPADTONE_LIST[tmpkeypadtone]))
        basic.append(rs)

        #Language
        tmplanguage=_mem.language
        if tmplanguage>=len(LANGUAGE_LIST):
            tmplanguage=0
        rs = RadioSetting("language", "Language", RadioSettingValueList( LANGUAGE_LIST, LANGUAGE_LIST[tmplanguage]))
        basic.append(rs)

        # Alarm mode
        tmpalarmmode=_mem.alarm_mode
        if tmpalarmmode>=len(ALARMMODE_LIST):
            tmpalarmmode=0
        rs = RadioSetting("alarm_mode", "Alarm mode", RadioSettingValueList( ALARMMODE_LIST, ALARMMODE_LIST[tmpalarmmode]))
        basic.append(rs)

        # Reminding of end of talk
        tmpalarmmode=_mem.reminding_of_end_talk
        if tmpalarmmode>=len(REMENDOFTALK_LIST):
            tmpalarmmode=0
        rs = RadioSetting("reminding_of_end_talk", "Reminding of end of talk", RadioSettingValueList( REMENDOFTALK_LIST, REMENDOFTALK_LIST[tmpalarmmode]))
        basic.append(rs)

        # Repeater tail tone elimination
        tmprte=_mem.repeater_tail_elimination
        if tmprte>=len(RTE_LIST):
            tmprte=0
        rs = RadioSetting("repeater_tail_elimination", "Repeater tail tone elimination", RadioSettingValueList( RTE_LIST, RTE_LIST[tmprte]))
        basic.append(rs)

        #Logo string 1
        logo1=str(_mem.logo_line1).strip("\x20\x00\xff") #+"\x20"*12
        logo1=logo1[0:12]
        rs = RadioSetting("logo1", "Logo string 1 (12 characters)", RadioSettingValueString(0,12,logo1))
        basic.append(rs)


        #Logo string 2
        logo2=str(_mem.logo_line2).strip("\x20\x00\xff") #+"\x20"*12
        logo2=logo2[0:12]
        rs = RadioSetting("logo2", "Logo string 2 (12 characters)", RadioSettingValueString(0,12,logo2))
        basic.append(rs)





####unlock settings

        # F-LOCK
        tmpflock=_mem.int_flock
        if tmpflock>=len(FLOCK_LIST):
            tmpflock=0
        rs = RadioSetting("flock", "F-LOCK", RadioSettingValueList( FLOCK_LIST, FLOCK_LIST[tmpflock]))
        unlock.append(rs)

        #350TX
        rs = RadioSetting("350tx", "350TX", RadioSettingValueBoolean(bool(_mem.int_350tx>0)))
        unlock.append(rs)

        #unknown1
        rs = RadioSetting("unknown11", "UNKNOWN1", RadioSettingValueBoolean(bool(_mem.int_unknown1>0)))
        unlock.append(rs)

        #200TX
        rs = RadioSetting("200tx", "200TX", RadioSettingValueBoolean(bool(_mem.int_200tx>0)))
        unlock.append(rs)

        #500TX
        rs = RadioSetting("500tx", "500TX", RadioSettingValueBoolean(bool(_mem.int_500tx>0)))
        unlock.append(rs)

        #350EN
        rs = RadioSetting("350en", "350EN", RadioSettingValueBoolean(bool(_mem.int_350en>0)))
        unlock.append(rs)

        #SCREEN
        rs = RadioSetting("screen", "SCREEN", RadioSettingValueBoolean(bool(_mem.int_screen>0)))
        unlock.append(rs)

### readonly info
# Firmware
        if self.FIRMWARE_VERSION=="":
            firmware="To get the firmware version please download the image from the radio first"
        else:
            firmware=self.FIRMWARE_VERSION
        rs = RadioSetting("fw_ver", "Firmware Version", RadioSettingValueString(0,128,firmware))
        roinfo.append(rs)

# Driver version
        rs = RadioSetting("driver_ver", "Driver version", RadioSettingValueString(0,128,DRIVER_VERSION))
        roinfo.append(rs)

        return top

    # Store details about a high-level memory to the memory map
    # This is called when a user edits a memory in the UI
    def set_memory(self, mem):
        number=mem.number-1


        #print("set_memory ch=",mem.number);
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.channel[number]
        #empty memory
        if mem.empty:
            _mem.set_raw("\xFF" * 16)
            if number<200:
                _mem2 = self._memobj.channelname[number]
                _mem2.set_raw("\xFF" * 16)
            return mem

        # mode
        if mem.mode == "AM":
            _mem.flags1 = _mem.flags1 | FLAGS1_ISAM
            _mem.flags2 = _mem.flags2 & ~FLAGS2_BANDWIDTH
        else:
            _mem.flags1 = _mem.flags1 & ~FLAGS1_ISAM
            if mem.mode == "NFM":
                _mem.flags2 = _mem.flags2 | FLAGS2_BANDWIDTH
            else:
                _mem.flags2 = _mem.flags2 & ~FLAGS2_BANDWIDTH

        # frequency/offset
        _mem.freq = mem.freq/10
        _mem.offset = mem.offset/10

        if mem.duplex == "off":
            _mem.offset=0
        elif mem.duplex == '-':
            _mem.flags1=_mem.flags1|FLAGS1_OFFSET
        elif mem.duplex == '+':
            _mem.flags1=_mem.flags1&~FLAGS1_OFFSET

        #channels >200 are the 14 VFO chanells and don't have names
        if number<200:
            _mem2 = self._memobj.channelname[number]
            tag=mem.name.ljust(16)[:16]
            #print("tag=",tag)
            _mem2.name = tag  # Store the alpha tag

                    # tone data
        self._set_tone(mem, _mem)

        # step
        _mem.step=STEPS.index(mem.tuning_step)<<1

        # tx power
        if str(mem.power) == "High":
            _mem.flags2 = (_mem.flags2 & ~FLAGS2_POWER_MASK ) | FLAGS2_POWER_HIGH
        elif str(mem.power) == "Med":
            _mem.flags2 = (_mem.flags2 & ~FLAGS2_POWER_MASK ) | FLAGS2_POWER_MEDIUM
        else:
            _mem.flags2 = (_mem.flags2 & ~FLAGS2_POWER_MASK ) 


        for setting in mem.extra:
            sname=setting.get_name()
            svalue=setting.value.get_value()
            #print("set_memory extra name",sname," value",svalue)

            if sname == "bclo":
                if svalue:
                    _mem.flags2 = _mem.flags2 | FLAGS2_BCLO
                else:
                    _mem.flags2 = _mem.flags2 & ~FLAGS2_BCLO

            if sname == "pttid":
                _mem.dtmf_flags = (_mem.dtmf_flags & ~FLAGS_DTMF_PTTID_MASK) | (PTTID_LIST.index(svalue)<<1)

            if sname == "frev":
                if svalue:
                    _mem.flags2 = _mem.flags2 | FLAGS2_REVERSE;
                else:
                    _mem.flags2 = _mem.flags2 & ~FLAGS2_REVERSE;

            if sname == "dtmfdecode":
                if svalue:
                    _mem.dtmf_flags = _mem.dtmf_flags | FLAGS_DTMF_DECODE;
                else:
                    _mem.dtmf_flags = _mem.dtmf_flags & ~FLAGS_DTMF_DECODE;

            if sname == "scrambler":
                _mem.scrambler = (_mem.scrambler & 0xf0) | SCRAMBLER_LIST.index(svalue)




        return mem #not sure if needed?
