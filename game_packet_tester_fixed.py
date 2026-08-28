import wx
import socket
import struct
import threading
import time
import hashlib
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5, DES

# RSA Private Key parameters extracted from game.ai
MODULUS = 2536390877856991809364935906928198678924093474659359277061605408649683520940966982836776970628314247132453935687650297819698921885002587537531650245796815651578388676113966938341719
PRIVATE_EXPONENT = 2392381990411642365193751285879328158694657403139340419470531149443655286791992538734427956972231381018780883038873762325527026819683631504059774416719403096901939434884961099280065
PUBLIC_EXPONENT = 65537

rsa_key = RSA.construct((MODULUS, PUBLIC_EXPONENT, PRIVATE_EXPONENT))
rsa_cipher = PKCS1_v1_5.new(rsa_key)

def pad(data: bytes) -> bytes:
    block_size = 8
    padding_len = block_size - (len(data) % block_size)
    return data + bytes([padding_len] * padding_len)

def unpad(data: bytes) -> bytes:
    if not data:
        return data
    padding_len = data[-1]
    if padding_len > 8 or padding_len == 0:
        return data
    return data[:-padding_len]

def get_md5(text: str) -> bytes:
    return hashlib.md5(text.encode('utf-8')).digest()

def get_fake_hwid() -> bytes:
    fake_mac_data = b"Desktop-PC-001122334455"
    mutated = bytearray(fake_mac_data)
    mutated[0] = mutated[0] | 0x61
    return hashlib.md5(mutated).digest()


class GamePacketFrame(wx.Frame):
    def __init__(self):
        super().__init__(parent=None, title="Netty-Targeted Game Packet Tester v6 (Enhanced Debug)", size=(1000, 850))
        
        self.sock = None
        self.des_key = b'\x00' * 8  
        self.is_connected = False
        self.last_response = None

        self.init_ui()
        self.Center()
        self.Show()

    def init_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Connection Box ---
        conn_box = wx.StaticBox(panel, label="Server Connection")
        conn_sizer = wx.StaticBoxSizer(conn_box, wx.HORIZONTAL)

        conn_sizer.Add(wx.StaticText(panel, label=" Host:"), flag=wx.ALIGN_CENTER_VERTICAL)
        self.host_ctrl = wx.TextCtrl(panel, value="148.113.174.207", size=(140, -1))
        conn_sizer.Add(self.host_ctrl, flag=wx.LEFT|wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=5)

        conn_sizer.Add(wx.StaticText(panel, label=" Port:"), flag=wx.ALIGN_CENTER_VERTICAL)
        self.port_ctrl = wx.TextCtrl(panel, value="8769", size=(60, -1))
        conn_sizer.Add(self.port_ctrl, flag=wx.LEFT|wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, border=5)

        self.connect_btn = wx.Button(panel, label="Connect & Handshake")
        self.connect_btn.Bind(wx.EVT_BUTTON, self.on_toggle_connection)
        conn_sizer.Add(self.connect_btn, flag=wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=10)

        self.status_lbl = wx.StaticText(panel, label="Status: Disconnected")
        self.status_lbl.SetForegroundColour(wx.Colour(200, 0, 0))
        conn_sizer.Add(self.status_lbl, flag=wx.LEFT|wx.ALIGN_CENTER_VERTICAL, border=15)

        main_sizer.Add(conn_sizer, flag=wx.ALL|wx.EXPAND, border=10)

        # --- Packet Builder Box ---
        builder_box = wx.StaticBox(panel, label="Netty Packet Builder")
        builder_sizer = wx.StaticBoxSizer(builder_box, wx.VERTICAL)

        grid_sizer = wx.FlexGridSizer(rows=6, cols=2, vgap=8, hgap=8)
        grid_sizer.AddGrowableCol(1, 1)

        grid_sizer.Add(wx.StaticText(panel, label="OpCode (1-byte):"), flag=wx.ALIGN_CENTER_VERTICAL)
        self.opcode_ctrl = wx.TextCtrl(panel, value="1", size=(80, -1))
        grid_sizer.Add(self.opcode_ctrl, flag=wx.EXPAND)

        grid_sizer.Add(wx.StaticText(panel, label="Writing Method:"), flag=wx.ALIGN_CENTER_VERTICAL)
        self.methods = [
            "Login Secure (User String + MD5 Pass Bytes + HWID Bytes)",
            "writeUTF (Java String)",
            "writeInt (4-byte Int)",
            "Raw Hex Bytes"
        ]
        self.method_cb = wx.ComboBox(panel, choices=self.methods, style=wx.CB_READONLY)
        self.method_cb.SetSelection(0)
        self.method_cb.Bind(wx.EVT_COMBOBOX, self.on_method_change)
        grid_sizer.Add(self.method_cb, flag=wx.EXPAND)

        grid_sizer.Add(wx.StaticText(panel, label="Username:"), flag=wx.ALIGN_CENTER_VERTICAL)
        self.payload_ctrl = wx.TextCtrl(panel, value="testuser")
        grid_sizer.Add(self.payload_ctrl, flag=wx.EXPAND)

        self.pass_label = wx.StaticText(panel, label="Password:")
        self.pass_ctrl = wx.TextCtrl(panel, value="testpass", style=wx.TE_PASSWORD)
        grid_sizer.Add(self.pass_label, flag=wx.ALIGN_CENTER_VERTICAL)
        grid_sizer.Add(self.pass_ctrl, flag=wx.EXPAND)

        self.debug_chk = wx.CheckBox(panel, label="Show Debug Hex Output")
        grid_sizer.Add(self.debug_chk, flag=wx.ALIGN_CENTER_VERTICAL)
        grid_sizer.Add(wx.StaticText(panel, label=""))

        builder_sizer.Add(grid_sizer, flag=wx.ALL|wx.EXPAND, border=5)

        self.send_btn = wx.Button(panel, label="Build & Send Netty Frame")
        self.send_btn.Bind(wx.EVT_BUTTON, self.on_send_packet)
        self.send_btn.Enable(False)
        builder_sizer.Add(self.send_btn, flag=wx.TOP|wx.BOTTOM, border=5)

        main_sizer.Add(builder_sizer, flag=wx.ALL|wx.EXPAND, border=10)

        # --- Console Log Box ---
        log_box = wx.StaticBox(panel, label="Network Console Log")
        log_sizer = wx.StaticBoxSizer(log_box, wx.VERTICAL)

        self.console = wx.TextCtrl(panel, style=wx.TE_MULTILINE|wx.TE_READONLY|wx.TE_RICH2)
        self.console.SetBackgroundColour(wx.Colour(30, 30, 30))
        self.console.SetForegroundColour(wx.Colour(0, 255, 0))
        log_sizer.Add(self.console, proportion=1, flag=wx.ALL|wx.EXPAND, border=5)

        main_sizer.Add(log_sizer, proportion=1, flag=wx.ALL|wx.EXPAND, border=10)

        panel.SetSizer(main_sizer)
        self.log("Tester initialized. Connect and try login.")

    def log(self, msg):
        wx.CallAfter(self.console.AppendText, msg + "\n")

    def on_method_change(self, event):
        if "Login Secure" in self.method_cb.GetStringSelection():
            self.pass_label.Show(True)
            self.pass_ctrl.Show(True)
        else:
            self.pass_label.Show(False)
            self.pass_ctrl.Show(False)
        self.Layout()

    def on_toggle_connection(self, event):
        if not self.is_connected:
            host = self.host_ctrl.GetValue()
            try:
                port = int(self.port_ctrl.GetValue())
            except ValueError:
                wx.MessageBox("Invalid port number.", "Error", wx.OK | wx.ICON_ERROR)
                return
            threading.Thread(target=self.connect_server, args=(host, port), daemon=True).start()
        else:
            try:
                if self.sock:
                    self.sock.close()
            except:
                pass
            self.is_connected = False
            self.connect_btn.SetLabel("Connect & Handshake")
            self.status_lbl.SetLabel("Status: Disconnected")
            self.status_lbl.SetForegroundColour(wx.Colour(200, 0, 0))
            self.send_btn.Enable(False)
            self.log("Disconnected.")

    def connect_server(self, host, port):
        try:
            self.log(f"Connecting to {host}:{port}...")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(6.0)
            self.sock.connect((host, port))
            
            # Read RSA Handshake payload
            header = self.read_exact(4)
            (payload_length,) = struct.unpack(">I", header)
            self.log(f"[Handshake] Server sent RSA payload length: {payload_length} bytes")
            raw_payload = self.read_exact(payload_length)

            decrypted_rsa = rsa_cipher.decrypt(raw_payload, None)
            if decrypted_rsa is None:
                raise ValueError("RSA Handshake decryption failed - invalid key or corrupted payload.")
                
            self.des_key = decrypted_rsa[:8]
            self.log(f"[Handshake Success] DES Key received: {self.des_key.hex()}")
            self.log(f"[Handshake] Full decrypted payload ({len(decrypted_rsa)} bytes): {decrypted_rsa.hex()}")
            
            self.is_connected = True
            self.sock.settimeout(None)
            
            wx.CallAfter(self.status_lbl.SetLabel, "Status: Connected")
            wx.CallAfter(self.status_lbl.SetForegroundColour, wx.Colour(0, 150, 0))
            wx.CallAfter(self.connect_btn.SetLabel, "Disconnect")
            wx.CallAfter(self.send_btn.Enable, True)

            threading.Thread(target=self.receive_loop, daemon=True).start()
        except Exception as e:
            self.log(f"[Connection Error] {e}")
            self.is_connected = False
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass

    def read_exact(self, length):
        data = bytearray()
        while len(data) < length:
            packet = self.sock.recv(length - len(data))
            if not packet:
                raise ConnectionResetError("Connection closed by server.")
            data.extend(packet)
        return bytes(data)

    def receive_loop(self):
        try:
            buffer = bytearray()
            while self.is_connected:
                chunk = self.sock.recv(4096)
                if not chunk:
                    self.log("[Connection] Server closed connection.")
                    break
                buffer.extend(chunk)
                
                while len(buffer) >= 4:
                    (payload_length,) = struct.unpack(">I", buffer[:4])
                    if len(buffer) < 4 + payload_length:
                        break  
                    
                    raw_payload = bytes(buffer[4:4 + payload_length])
                    del buffer[:4 + payload_length]

                    try:
                        des_cipher = DES.new(self.des_key, DES.MODE_ECB)
                        decrypted_payload = des_cipher.decrypt(raw_payload)
                        unpadded = unpad(decrypted_payload)

                        opcode = unpadded[0] if unpadded else 0x00
                        body = unpadded[1:] if len(unpadded) > 1 else b""

                        self.log(f"\n[Received] OpCode: 0x{opcode:02x} ({opcode})")
                        self.log(f"[Received] Raw HEX: {unpadded.hex()}")
                        
                        # Interpret response
                        if opcode == 0x01:
                            self.log("[Server Response] Login REJECTED (0x01)")
                            self.log("[Debug] Response body: " + body.hex() if body else "[Debug] No response body")
                        elif opcode == 0x00:
                            self.log("[Server Response] Login SUCCESS (0x00)")
                        else:
                            try:
                                text = unpadded.decode('utf-8', errors='replace')
                                self.log(f"[Received] Text: {text}")
                            except:
                                self.log(f"[Received] Body (non-UTF8): {body.hex()}")
                    except Exception as decode_err:
                        self.log(f"[Decryption/Decode Error] {decode_err}")
        except Exception as e:
            if self.is_connected:
                self.log(f"\n[Connection Lost]: {e}")
                self.is_connected = False

    def on_send_packet(self, event):
        if not self.is_connected:
            self.log("[Error] Not connected to server.")
            return
        try:
            opcode = int(self.opcode_ctrl.GetValue())
            method = self.method_cb.GetStringSelection()
            username = self.payload_ctrl.GetValue()

            payload_body = b""
            if "Login Secure" in method:
                user_enc = username.encode('utf-8')
                user_bytes = struct.pack(">H", len(user_enc)) + user_enc
                pass_md5_bytes = get_md5(self.pass_ctrl.GetValue())
                hwid_bytes = get_fake_hwid()
                payload_body = user_bytes + pass_md5_bytes + hwid_bytes
                
                if self.debug_chk.GetValue():
                    self.log(f"\n[Debug] Username bytes: {user_bytes.hex()}")
                    self.log(f"[Debug] Password MD5: {pass_md5_bytes.hex()}")
                    self.log(f"[Debug] HWID bytes: {hwid_bytes.hex()}")
                    
            elif "writeUTF" in method:
                encoded = username.encode('utf-8')
                payload_body = struct.pack(">H", len(encoded)) + encoded
            elif "writeInt" in method:
                payload_body = struct.pack(">I", int(username))
            elif "Raw Hex" in method:
                payload_body = bytes.fromhex(username.strip().replace(" ", ""))

            full_data_array = bytes([opcode]) + payload_body
            to_encrypt = full_data_array[1:] if len(full_data_array) > 1 else b""
            padded_data = pad(to_encrypt)
            des_cipher = DES.new(self.des_key, DES.MODE_ECB)
            encrypted_payload = des_cipher.encrypt(padded_data)

            frame_length = len(encrypted_payload) + 1
            frame = struct.pack(">I", frame_length) + bytes([opcode]) + encrypted_payload
            
            self.sock.sendall(frame)
            self.log(f"\n[Sent Netty Frame] OpCode: 0x{opcode:02x} ({opcode})")
            self.log(f"[Sent] Frame length field: {frame_length} bytes")
            
            if self.debug_chk.GetValue():
                self.log(f"[Debug] Full plaintext (opcode + payload): {full_data_array.hex()}")
                self.log(f"[Debug] Padded for encryption: {padded_data.hex()}")
                self.log(f"[Debug] Encrypted payload: {encrypted_payload.hex()}")

        except Exception as e:
            self.log(f"[Send Error] {e}")

if __name__ == "__main__":
    app = wx.App()
    GamePacketFrame()
    app.MainLoop()
