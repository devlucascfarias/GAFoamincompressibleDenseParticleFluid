import os
import sys
import re
import numpy as np
import pyqtgraph as pg
import json
import psutil
from PyQt5.QtWidgets import (QApplication, QWidget,QComboBox, QWidgetAction, QPushButton, QVBoxLayout, QHBoxLayout, 
                             QFileDialog, QTextEdit, QLabel, QMenuBar, QMenu, QAction, 
                             QLineEdit, QStatusBar, QDialog, QTableWidget, QTableWidgetItem, QMessageBox, QInputDialog)
from PyQt5.QtCore import QTimer, QProcess, Qt, QDir, QFileInfo, QProcessEnvironment
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QIcon
from PyQt5 import QtCore
import signal # Added import

from rate_calculator import calculate_increase_rate
from syntax_highlighter import OpenFOAMHighlighter
from simulation_history import SimulationHistory
from datetime import datetime

class OpenFOAMInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GAFoam — incompressibleDenseParticleFluid")
        self.resize(1000, 600)

        self.config_file = "config.json"
        self.config = self.load_config()

        """
        
        === PATH CONFIGURATION ===
        
        """

        loaded_base_dir = self.config.get("baseDir", "") 
        if not loaded_base_dir or not os.path.isdir(loaded_base_dir):
            loaded_base_dir = os.getcwd() 
        self.baseDir = loaded_base_dir
        
        self.systemDir = os.path.join(self.baseDir, "system")
        self.unvFilePath = ""
        self.currentFilePath = ""
        self.currentOpenFOAMVersion = self.config.get("openFOAMVersion", "openfoam12")
        self.currentSolver = "incompressibleDenseParticleFluid"
        self.currentProcess = None
        
        """ 
        
        === DATA FOR RESIDUAL PLOT ===
        
        """

        self.residualData = {}
        self.timeData = []
        self.residualLines = {}
        self.colors = ['r', 'g', 'b', 'c', 'm', 'y', 'w']
        # Adiciona armazenamento para max(cloud:alpha)
        self.maxCloudAlphaData = []
        self.maxCloudAlphaLine = None 
        
        self.mainVerticalLayout = QVBoxLayout(self)
        self.mainVerticalLayout.setContentsMargins(5, 5, 5, 5)
        
        self.setupMenuBar()
        self.setupMainContentArea()
        self.setupStatusBar()
        
        self.systemMonitorTimer = QTimer(self)
        self.systemMonitorTimer.timeout.connect(self.updateSystemUsage)
        self.systemMonitorTimer.start(2000)
        
        self.setLayout(self.mainVerticalLayout)
        self.simulationHistory = SimulationHistory()

    # def openFileEditor(self):
    #     """Abre a janela separada para o editor de arquivos."""
    #     self.fileEditorWindow = FileEditorWindow(self.baseDir, self)
    #     self.fileEditorWindow.show()
    
    def detectOpenFOAMVersions(self):
        versions = []
        openfoamDir = QDir("/opt")
        
        filters = ["openfoam*", "OpenFOAM*"]
        for dirName in openfoamDir.entryList(filters, QDir.Dirs | QDir.NoDotAndDotDot):
            versions.append(dirName)
        
        if not versions:
            versions.append("openfoam12")
            print("Warning: No OpenFOAM version found in /opt. Using fallback.")
        
        return versions
    
    def clearOldProcessorDirs(self):
        caseDir = QDir(self.baseDir)
        
        processorDirs = caseDir.entryList(["processor*"], QDir.Dirs | QDir.NoDotAndDotDot)
        for dirName in processorDirs:
            processorDir = QDir(caseDir.filePath(dirName))
            if processorDir.removeRecursively():
                self.outputArea.append(f"Removing old folder: {dirName}")

    def chooseUNV(self):
        unvFilePath, _ = QFileDialog.getOpenFileName(
            self,
            "Choose .unv File",
            "",
            "UNV Files (*.unv)"
        )
        
        if unvFilePath:
            self.unvFilePath = unvFilePath
            self.outputArea.append(f".unv file loaded: {unvFilePath}")
            self.meshPathLabel.setText(f"Mesh: {QFileInfo(unvFilePath).fileName()}")
        else:
            self.outputArea.append("No .unv file was selected.")    

    
    def chooseCase(self):
        casePath = QFileDialog.getExistingDirectory(
            self, 
            "Choose Case Folder", 
            self.baseDir,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if casePath:
            required_dirs = ["0", "system", "constant"]
            if all(QDir(casePath).exists(dir_name) for dir_name in required_dirs):
                self.unvFilePath = casePath  
                self.baseDir = casePath  # Adiciona esta linha para sincronizar baseDir
                self.systemDir = os.path.join(self.baseDir, "system")
                self.config["baseDir"] = self.baseDir
                self.save_config()
                self.outputArea.append(f"Case folder selected: {casePath}")
                self.meshPathLabel.setText(f"Mesh: {QFileInfo(casePath).fileName()}")
                self.outputArea.append("Case loaded successfully.")
                # self.populateTreeView(casePath)  
            else:
                self.outputArea.append("Error: The selected folder does not contain the required directories (0, system, constant).")
        else:
            self.outputArea.append("No folder was selected.")
    
    def setupMenuBar(self):
        self.menuBar = QMenuBar(self)
        self.menuBar.setStyleSheet("""
            QMenuBar {
                background-color: #2c3e50;
                color: white;
                border: 1px solid #34495e;
                padding: 4px;
                font-weight: bold;
            }
            QMenuBar::item {
                background-color: transparent;
                padding: 8px 12px;
                border-radius: 4px;
            }
            QMenuBar::item:selected {
                background-color: #3498db;
                color: white;
            }
            QMenuBar::item:pressed {
                background-color: #2980b9;
            }
        """)
        
        fileMenu = QMenu("File", self.menuBar)
        fileMenu.setStyleSheet("""
            QMenu {
                background-color: #34495e;
                color: white;
                border: 1px solid #3498db;
                border-radius: 4px;
                padding: 5px;
            }
            QMenu::item {
                background-color: transparent;
                padding: 8px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #3498db;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background-color: #3498db;
                margin: 5px 0px;
            }
        """)
        
        refreshTreeAction = QAction("Refresh Tree", self)
        refreshTreeAction.triggered.connect(lambda: self.populateTreeView(QFileInfo(self.unvFilePath).absolutePath() if self.unvFilePath else None))
        
        importUNVAction = QAction("Load .unv File", self)
        importUNVAction.triggered.connect(self.chooseUNV)
        
        importCaseAction = QAction("Load Case", self)
        importCaseAction.triggered.connect(self.chooseCase)
        
        fileMenu.addAction(refreshTreeAction)
        fileMenu.addAction(importUNVAction)
        fileMenu.addAction(importCaseAction)
        
        self.menuBar.addMenu(fileMenu)
        self.mainVerticalLayout.setMenuBar(self.menuBar)
        
        terminalMenu = QMenu("Terminal", self.menuBar)
        
        clearTerminalAction = QAction("Clear Terminal", self)
        clearTerminalAction.triggered.connect(self.clearTerminal)
        
        terminalMenu.addAction(clearTerminalAction)
        
        openfoamMenu = QMenu("OpenFOAM", self.menuBar)
        
        self.versionComboBox = QComboBox(self)
        self.versionComboBox.setStyleSheet("""
            QComboBox {
                background-color: #34495e;
                color: white;
                border: 1px solid #3498db;
                border-radius: 4px;
                padding: 5px 10px;
                font-weight: bold;
                min-width: 120px;
            }
            QComboBox:hover {
                background-color: #3498db;
                border-color: #2980b9;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: url(down_arrow.png);
                width: 12px;
                height: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #34495e;
                color: white;
                border: 1px solid #3498db;
                selection-background-color: #3498db;
                outline: none;
            }
        """)
        self.versionComboBox.addItems(self.detectOpenFOAMVersions())
        self.versionComboBox.setCurrentText(self.currentOpenFOAMVersion)
        self.versionComboBox.currentTextChanged.connect(self.setOpenFOAMVersion)
        
        versionAction = QWidgetAction(openfoamMenu)
        versionAction.setDefaultWidget(self.versionComboBox)
        openfoamMenu.addAction(versionAction)
        
        self.menuBar.addMenu(fileMenu)
        self.menuBar.addMenu(terminalMenu)
        self.menuBar.addMenu(openfoamMenu)
        
        historyMenu = QMenu("History", self.menuBar)
        viewHistoryAction = QAction("View Simulation History", self)
        viewHistoryAction.triggered.connect(self.openSimulationHistory)
        historyMenu.addAction(viewHistoryAction)
        self.menuBar.addMenu(historyMenu)
        
        self.mainVerticalLayout.setMenuBar(self.menuBar)

        setBaseDirAction = QAction("Set Base Directory", self)
        setBaseDirAction.triggered.connect(self.set_base_dir)
        fileMenu.addAction(setBaseDirAction)
    
    def setOpenFOAMVersion(self, version):
        self.currentOpenFOAMVersion = version
        self.outputArea.append(f"Selected version: {version}")
    
    def setupMainContentArea(self):

        contentLayout = QHBoxLayout()
        
        ''' 
        
        === SIMULATION CONTROL BUTTONS (LEFT) ===
        
        '''

        leftControlLayout = QVBoxLayout()

        # Main simulation control buttons with icons and styling
        self.convertButton = QPushButton("⟺ Convert Mesh", self)
        self.convertButton.setStyleSheet("""
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                border: 2px solid #00796B;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #00796B;
            }
            QPushButton:pressed {
                background-color: #00695C;
            }
        """)
        self.convertButton.clicked.connect(self.convertMesh)
        leftControlLayout.addWidget(self.convertButton)
        
        self.checkMeshButton = QPushButton("✓ Check Mesh", self)
        self.checkMeshButton.setStyleSheet("""
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                border: 2px solid #00796B;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #00796B;
            }
            QPushButton:pressed {
                background-color: #00695C;
            }
        """)
        self.checkMeshButton.clicked.connect(self.checkMesh)
        leftControlLayout.addWidget(self.checkMeshButton)
        
        self.decomposeParButton = QPushButton("⚡ Decompose Cores", self)
        self.decomposeParButton.setStyleSheet("""
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                border: 2px solid #00796B;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #00796B;
            }
            QPushButton:pressed {
                background-color: #00695C;
            }
        """)
        self.decomposeParButton.clicked.connect(self.decomposePar)
        leftControlLayout.addWidget(self.decomposeParButton)
        
        self.reconstructButton = QPushButton("⚙️ Reconstruct", self)
        self.reconstructButton.setStyleSheet("""
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                border: 2px solid #00796B;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #00796B;
            }
            QPushButton:pressed {
                background-color: #00695C;
            }
        """)
        self.reconstructButton.clicked.connect(self.reconstructPar)
        leftControlLayout.addWidget(self.reconstructButton)
        
        self.clearDecomposeButton = QPushButton("🗑️ Clear Processors", self)
        self.clearDecomposeButton.setStyleSheet("""
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                border: 2px solid #00796B;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #00796B;
            }
            QPushButton:pressed {
                background-color: #00695C;
            }
        """)
        self.clearDecomposeButton.clicked.connect(self.clearDecomposedProcessors)
        leftControlLayout.addWidget(self.clearDecomposeButton)
        
        self.clearSimulationButton = QPushButton("🗑️ Clear Simulation Files", self)
        self.clearSimulationButton.setStyleSheet("""
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                border: 2px solid #00796B;
                font-weight: bold;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #00796B;
            }
            QPushButton:pressed {
                background-color: #00695C;
            }
        """)
        self.clearSimulationButton.clicked.connect(self.clearSimulation)
        leftControlLayout.addWidget(self.clearSimulationButton)
        
        self.setCoresButton = QPushButton("⚙️ Set Cores for decomposePar", self)
        self.setCoresButton.setStyleSheet("""
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                border: 2px solid #00796B;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #00796B;
            }
            QPushButton:pressed {
                background-color: #00695C;
            }
        """)
        self.setCoresButton.clicked.connect(self.configureDecomposeParCores)
        leftControlLayout.addWidget(self.setCoresButton)
        
        self.logButton = QPushButton("📊 Show Logs (log.foamRun)", self)
        self.logButton.setStyleSheet("""
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                border: 2px solid #00796B;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #00796B;
            }
            QPushButton:pressed {
                background-color: #00695C;
            }
        """)
        self.logButton.clicked.connect(self.showSimulationLogs)
        leftControlLayout.addWidget(self.logButton)

        # Add stretch to push buttons to top
        leftControlLayout.addStretch()
        
        ''' 
        
        === TERMINAL AND PLOT (RIGHT) ===
        
        '''

        rightContentLayout = QVBoxLayout()
        
        # Utility buttons at the top right with icons and styling
        utilityButtonLayout = QHBoxLayout()
        
        # Simulation control buttons (Run, Pause, Resume, Restart, Stop)
        # Definindo tamanho padrão para todos os botões de simulação
        sim_button_width = 40
        sim_button_height = 36
        sim_button_style = """
            QPushButton {{
                min-width: {width}px;
                max-width: {width}px;
                min-height: {height}px;
                max-height: {height}px;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                border: 2px solid #00796B;
                text-align: center;
                font-size: 15px;
            }}
            QPushButton:pressed {{
                border: 2px solid #888;
            }}
        """.format(width=sim_button_width, height=sim_button_height)
        
        self.runButton = QPushButton("▶", self)
        self.runButton.setStyleSheet(sim_button_style + """
            QPushButton {
                background-color: #009688;
                color: white;
            }
            QPushButton:hover {
                background-color: #00796B;

            }
            QPushButton:pressed {
                background-color: #00796B;
            }
        """)
        self.runButton.clicked.connect(self.runSimulation)
        
        self.pauseButton = QPushButton("⏸", self)
        self.pauseButton.setStyleSheet(sim_button_style + """
            QPushButton {
                background-color: #FF9800;
                color: white;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
        """)
        self.pauseButton.clicked.connect(self.pauseSimulation)
        
        self.resumeButton = QPushButton("⏯", self)
        self.resumeButton.setStyleSheet(sim_button_style + """
            QPushButton {
                background-color: #009688;
                color: white;
            }
            QPushButton:hover {
                background-color: #00796B;

            }
            QPushButton:pressed {
                background-color: #00796B;
            }
        """)
        self.resumeButton.clicked.connect(self.resumeSimulation)
        
        self.restartButton = QPushButton("↻", self)
        self.restartButton.setStyleSheet(sim_button_style + """
            QPushButton {
                background-color: #2196F3;
                color: white;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #1565C0;
            }
        """)
        self.restartButton.clicked.connect(self.restartSimulation)
        self.restartButton.clicked.connect(self.clearResidualPlot)
        
        self.stopButton = QPushButton("⏹", self)
        self.stopButton.setStyleSheet(sim_button_style + """
            QPushButton {
                background-color: #f44336;
                color: white;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
            QPushButton:pressed {
                background-color: #c62828;
            }
        """)
        self.stopButton.clicked.connect(self.stopSimulation)
        
        # Add simulation control buttons
        utilityButtonLayout.addWidget(self.runButton)
        utilityButtonLayout.addWidget(self.pauseButton)
        utilityButtonLayout.addWidget(self.resumeButton)
        utilityButtonLayout.addWidget(self.restartButton)
        utilityButtonLayout.addWidget(self.stopButton)
        
        # Utility buttons - tamanho parametrizado
        utility_button_width = 180
        utility_button_height = 36
        utility_button_style = """
            QPushButton {{
                min-width: {width}px;
                max-width: {width}px;
                min-height: {height}px;
                max-height: {height}px;
                background-color: #009688;
                color: white;
                border: 2px solid #00796B;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                text-align: left;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #00796B;
            }}
            QPushButton:pressed {{
                background-color: #00695C;
            }}
        """.format(width=utility_button_width, height=utility_button_height)
        
        self.openParaviewButton = QPushButton("Open in ParaView", self)
        self.openParaviewButton.setStyleSheet(utility_button_style)
        self.openParaviewButton.clicked.connect(self.openParaview)
        
        self.calculateRateButton = QPushButton("Calculate Δy", self)
        self.calculateRateButton.setStyleSheet(utility_button_style)
        self.calculateRateButton.clicked.connect(self.openRateCalculationDialog)

        self.fluidPropertiesButton = QPushButton("Calculate Fluid Properties", self)
        self.fluidPropertiesButton.setStyleSheet(utility_button_style)
        self.fluidPropertiesButton.clicked.connect(self.openFluidPropertiesDialog)
        utilityButtonLayout.addWidget(self.openParaviewButton)
        utilityButtonLayout.addWidget(self.calculateRateButton)
        utilityButtonLayout.addWidget(self.fluidPropertiesButton)
        utilityButtonLayout.addStretch()  # Push buttons to left
        
        rightContentLayout.addLayout(utilityButtonLayout)
        
        # Terminal section
        terminalLayout = QVBoxLayout()
        
        terminal_title = QLabel("Terminal and Logs", self)
        terminal_title.setStyleSheet("""
            QLabel {
                background-color: #34495e;
                color: #ecf0f1;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #3498db;
                margin-bottom: 5px;
            }
        """)
        terminalLayout.addWidget(terminal_title)
        
        self.outputArea = QTextEdit(self)
        self.outputArea.setReadOnly(True)
        self.outputArea.setStyleSheet("""
            QTextEdit {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                font-size: 11px;
            }
        """)
        terminalLayout.addWidget(self.outputArea)
        
        self.terminalInput = QLineEdit(self)
        self.terminalInput.setPlaceholderText(">>")
        self.terminalInput.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px;
                font-family: 'Courier New', monospace;
            }
        """)
        self.terminalInput.returnPressed.connect(self.executeTerminalCommand)
        terminalLayout.addWidget(self.terminalInput)
        
        rightContentLayout.addLayout(terminalLayout)
        
        # Residual plot section        
        residualLayout = QVBoxLayout()
        
        plot_title = QLabel("Residual Plot", self)
        plot_title.setStyleSheet("""
            QLabel {
                background-color: #34495e;
                color: #ecf0f1;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #3498db;
                margin-bottom: 5px;
            }
        """)
        residualLayout.addWidget(plot_title)
        
        self.graphWidget = pg.PlotWidget()
        self.graphWidget.setBackground('w')
        self.graphWidget.setLabel('left', 'Residuals')
        self.graphWidget.setLabel('bottom', 'Time')
        self.graphWidget.setLogMode(y=True)  
        self.graphWidget.showGrid(x=True, y=True)
        self.graphWidget.addLegend()
        residualLayout.addWidget(self.graphWidget)
        
        graphControlLayout = QHBoxLayout()

        self.clearPlotButton = QPushButton("Clear Plot", self)
        self.clearPlotButton.setStyleSheet("""
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                text-align: center;
            }
            QPushButton:hover {
                background-color: #00796B;
            }
            QPushButton:pressed {
                background-color: #00695C;
            }
        """)
        self.clearPlotButton.clicked.connect(self.clearResidualPlot)

        self.exportPlotDataButton = QPushButton("Export Data", self)
        self.exportPlotDataButton.setStyleSheet("""
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                text-align: center;
            }
            QPushButton:hover {
                background-color: #00796B;
            }
            QPushButton:pressed {
                background-color: #00695C;
            }
        """)
        self.exportPlotDataButton.clicked.connect(self.exportPlotData)  

        graphControlLayout.addWidget(self.clearPlotButton)
        graphControlLayout.addWidget(self.exportPlotDataButton)

        residualLayout.addLayout(graphControlLayout)
        
        # --- Painel de Profiling de Performance ---
        profilingPanel = QVBoxLayout()
        profilingTitle = QLabel("Profiling de Performance", self)
        profilingTitle.setStyleSheet("""
            QLabel {
                background-color: #34495e;
                color: #ecf0f1;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #3498db;
                margin-bottom: 5px;
            }
        """)
        profilingPanel.addWidget(profilingTitle)
        profilingDesc = QLabel("Ative o profiling para medir o tempo gasto em cada etapa do solver.")
        profilingDesc.setWordWrap(True)
        profilingDesc.setStyleSheet("color: #ecf0f1; font-size: 11px; padding: 5px;")
        profilingPanel.addWidget(profilingDesc)
        self.profilingButton = QPushButton("Ativar Profiling", self)
        self.profilingButton.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
        """)
        self.profilingButton.clicked.connect(self.enableProfiling)
        profilingPanel.addWidget(self.profilingButton)
        
        # Área de logs de profiling
        self.profilingLogs = QTextEdit(self)
        self.profilingLogs.setReadOnly(True)
        self.profilingLogs.setMaximumHeight(200)
        self.profilingLogs.setStyleSheet("""
            QTextEdit {
                background-color: #2b2b2b;
                color: #00ff00;
                border: 1px solid #555555;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                font-size: 10px;
                padding: 5px;
            }
        """)
        self.profilingLogs.append("Profiling logs aparecerão aqui quando a simulação estiver rodando...")
        profilingPanel.addWidget(self.profilingLogs)
        
        profilingPanel.addStretch()
        profilingWidget = QWidget()
        profilingWidget.setLayout(profilingPanel)
        profilingWidget.setMaximumWidth(260)
        profilingWidget.setMinimumWidth(200)
        profilingWidget.setStyleSheet("background-color: #263238; border-radius: 6px; margin: 8px;")
        profilingAndPlotLayout = QHBoxLayout()
        profilingAndPlotLayout.addWidget(profilingWidget)
        profilingAndPlotLayout.addLayout(residualLayout)
        rightContentLayout.addLayout(profilingAndPlotLayout)
        # --- Fim do painel de profiling ---
        
        # Add layouts to main content with proper proportions
        contentLayout.addLayout(leftControlLayout, 1)  # Left side takes 1 part
        contentLayout.addLayout(rightContentLayout, 2)  # Right side takes 2 parts
        
        self.mainVerticalLayout.addLayout(contentLayout, 1)

        # self.treeUpdateTimer = QTimer(self)
        # self.treeUpdateTimer.timeout.connect(lambda: self.populateTreeView())
        # self.treeUpdateTimer.start(1000) 

    def toggleLogScale(self):
        """Toggles between linear and logarithmic scale on the Y-axis."""
        current = self.graphWidget.getViewBox().getState()['logMode'][1]
        self.graphWidget.setLogMode(y=not current)
        scale_type = "logarithmic" if not current else "linear"
        self.outputArea.append(f"{scale_type.capitalize()} scale activated", 2000)

    def exportPlotData(self):
        """Exports the plot data to a CSV file."""
        if not self.timeData:
            self.outputArea.append("No data to export", 2000)
            return
            
        fileName, _ = QFileDialog.getSaveFileName(
            self, "Save Residual Data", "", "CSV Files (*.csv)"
        )
        
        if fileName:
            with open(fileName, 'w') as f:
                header = "Time," + ",".join(self.residualData.keys())
                f.write(header + "\n")
                
                for i, time in enumerate(self.timeData):
                    line = f"{time}"
                    for var in self.residualData:
                        if i < len(self.residualData[var]):
                            value = self.residualData[var][i]
                            line += f",{value if value is not None else ''}"
                        else:
                            line += ","
                    f.write(line + "\n")
                    
            self.outputArea.append(f"Data exported to {fileName}")
        
    def onTreeViewDoubleClicked(self, index):
        """Abre a janela de edição de arquivos ao clicar em um arquivo na árvore."""
        item = self.treeModel.itemFromIndex(index)
        if item and not item.hasChildren(): 
            filePath = item.data(Qt.UserRole)
            if filePath:
                fileEditorWindow = FileEditorWindow(self.baseDir, self)
                fileEditorWindow.populateTreeView(self.baseDir)  
                fileEditorWindow.show()

                file = QtCore.QFile(filePath)
                if file.open(QtCore.QIODevice.ReadOnly | QtCore.QIODevice.Text):
                    fileEditorWindow.currentFilePath = filePath
                    fileEditorWindow.fileEditor.setPlainText(str(file.readAll(), 'utf-8'))
                    file.close()
    
    def setupStatusBar(self):
        self.statusBar = QStatusBar(self)
        self.statusBar.setStyleSheet("""
            QStatusBar {
                background-color: #34495e;
                color: white;
                border-top: 1px solid #3498db;
                padding: 5px;
                font-weight: bold;
            }
            QStatusBar::item {
                border: none;
                border-right: 1px solid #3498db;
                padding: 0px 10px;
            }
        """)
        
        # Styling individual labels
        label_style = """
            QLabel {
                background-color: transparent;
                color: #ecf0f1;
                padding: 5px 10px;
                border-radius: 3px;
                font-weight: bold;
                font-size: 11px;
            }
        """
        
        self.meshPathLabel = QLabel("Mesh: None", self.statusBar)
        self.meshPathLabel.setStyleSheet(label_style + "QLabel { color: #3498db; }")
        
        self.solverLabel = QLabel(f"Solver: {self.currentSolver}", self.statusBar)
        self.solverLabel.setStyleSheet(label_style + "QLabel { color: #2ecc71; }")
        
        self.cpuUsageLabel = QLabel("CPU: --%", self.statusBar)
        self.cpuUsageLabel.setStyleSheet(label_style + "QLabel { color: #f39c12; }")
        
        self.memUsageLabel = QLabel("Memory: --%", self.statusBar)
        self.memUsageLabel.setStyleSheet(label_style + "QLabel { color: #e74c3c; }")

        self.statusBar.addPermanentWidget(self.solverLabel, 1)
        self.statusBar.addPermanentWidget(self.meshPathLabel, 1)
        self.statusBar.addPermanentWidget(self.cpuUsageLabel)
        self.statusBar.addPermanentWidget(self.memUsageLabel)
        
        self.mainVerticalLayout.addWidget(self.statusBar)
    
    def updateSystemUsage(self):
        try:
            with open('/proc/stat', 'r') as f:
                lines = f.readlines()
                if lines:
                    values = lines[0].split()[1:]
                    if len(values) >= 4:
                        user, nice, system, idle = map(int, values[:4])
                        total = user + nice + system + idle
                        
                        if hasattr(self, 'lastTotal') and hasattr(self, 'lastIdle'):
                            deltaTotal = total - self.lastTotal
                            deltaIdle = idle - self.lastIdle
                            
                            if deltaTotal > 0 and self.lastTotal > 0:
                                cpuUsage = 100 * (deltaTotal - deltaIdle) / deltaTotal
                                self.cpuUsageLabel.setText(f"CPU: {int(cpuUsage)}%")
                        
                        self.lastTotal = total
                        self.lastIdle = idle
        except:
            pass
        
        storage = QtCore.QStorageInfo(QtCore.QDir.rootPath())
        memUsed = (storage.bytesTotal() - storage.bytesFree()) / (1024.0**3)
        memTotal = storage.bytesTotal() / (1024.0**3)
        memPercent = (memUsed / memTotal) * 100 if memTotal > 0 else 0
        
        self.memUsageLabel.setText(
            f"Memory: {int(memPercent)}% ({memUsed:.1f}G/{memTotal:.1f}G)"
        )
    
    def populateTreeView(self, casePath=None):
        if not casePath:
            casePath = QFileInfo(self.unvFilePath).absolutePath() if self.unvFilePath else self.baseDir
        
        self.treeModel = QStandardItemModel(self)
        rootItem = QStandardItem(QIcon.fromTheme("folder"), casePath)
        self.treeModel.appendRow(rootItem)
        self.addDirectoryToTree(casePath, rootItem)
        self.treeView.setModel(self.treeModel)
        self.treeView.expandAll()
    
    def addDirectoryToTree(self, path, parent):
        dir = QDir(path)
        dirName = dir.dirName()
        item = QStandardItem(dirName)
        
        item.setIcon(QIcon.fromTheme("folder"))
        parent.appendRow(item)
        
        filters = QDir.AllEntries | QDir.NoDotAndDotDot
        sorting = QDir.DirsFirst | QDir.Name | QDir.IgnoreCase
        
        for info in dir.entryInfoList(filters, sorting):
            if info.isDir():
                self.addDirectoryToTree(info.absoluteFilePath(), item)
            else:
                fileItem = QStandardItem(info.fileName())
                fileItem.setIcon(QIcon.fromTheme("text-x-generic"))
                item.appendRow(fileItem)
                fileItem.setData(info.absoluteFilePath(), Qt.UserRole)
    
    def openParaview(self):
        if not self.baseDir:
            self.outputArea.append("Erro: Nenhum caso selecionado")
            return
        foam_file = os.path.join(self.baseDir, "foam.foam")
        if not os.path.exists(foam_file):
            # Cria o arquivo vazio se não existir
            with open(foam_file, "w") as f:
                pass
            self.outputArea.append(f"Arquivo {foam_file} criado automaticamente.")
        command = f"paraview --data={foam_file}"
        process = QProcess(self)
        process.start(command)
        if not process.waitForStarted():
            self.outputArea.append("Erro ao abrir o ParaView")
        else:
            self.outputArea.append("ParaView iniciado com sucesso")
    
    def checkMesh(self):
        if not self.baseDir or not os.path.exists(self.baseDir):
            self.outputArea.append("Erro: Nenhum caso selecionado ou diretório base inválido.")
            return

        controlDictPath = os.path.join(self.baseDir, "system", "controlDict")
        if not os.path.exists(controlDictPath):
            self.outputArea.append(f"Erro: Arquivo controlDict não encontrado em {controlDictPath}.")
            return

        self.outputArea.append("Executando checkMesh...")
        command = f'source /opt/{self.currentOpenFOAMVersion}/etc/bashrc && checkMesh'

        process = QProcess(self)
        process.setWorkingDirectory(self.baseDir)
        self.setupProcessEnvironment(process)
        self.connectProcessSignals(process)
        self.outputArea.append(f"Comando executado: {command}")
        process.start("bash", ["-c", command])
    
    def convertMesh(self):
        if not self.unvFilePath:
            self.outputArea.append("Erro: Nenhum arquivo UNV selecionado")
            return

        self.outputArea.append("Convertendo malha para OpenFOAM...")
        command = f'source /opt/{self.currentOpenFOAMVersion}/etc/bashrc && ideasUnvToFoam {self.unvFilePath}'

        process = QProcess(self)
        process.setWorkingDirectory(self.baseDir)
        self.setupProcessEnvironment(process)
        self.connectProcessSignals(process)
        self.outputArea.append(f"Comando executado: {command}")
        process.start("bash", ["-c", command])
    
    def parseResiduals(self, line):
        """
        Analisa a saída do terminal para capturar resíduos e tempos.
        """
        # Captura dados de profiling e envia para o painel dedicado
        if "ExecutionTime" in line or "ClockTime" in line:
            self.profilingLogs.append(line)
        
        # Captura informações de timing específicas do solver
        if ("smoothSolver:" in line and "Solving for" in line) or ("GAMG:" in line and "Solving for" in line):
            if "Final residual" in line and "No Iterations" in line:
                # Extrai informações de performance
                parts = line.split(',')
                if len(parts) >= 3:
                    iterations_part = parts[2].strip()
                    if "No Iterations" in iterations_part:
                        iter_count = iterations_part.split()[-1]
                        solver_info = f"Solver performance: {iter_count} iterations"
                        self.profilingLogs.append(solver_info)
        
        current_time_match = re.search(r'Time = ([0-9.e+-]+)', line)
        if current_time_match:
            current_time = float(current_time_match.group(1))
            if current_time not in self.timeData:
                self.timeData.append(current_time)
                if len(self.maxCloudAlphaData) < len(self.timeData):
                    self.maxCloudAlphaData.append(None)

        residual_match = re.search(r'smoothSolver:  Solving for ([a-zA-Z0-9_.]+), Initial residual = ([0-9.e+-]+)', line)
        if residual_match:
            variable = residual_match.group(1)
            residual = float(residual_match.group(2))

            if variable not in self.residualData:
                self.residualData[variable] = []
                color_idx = len(self.residualData) % len(self.colors)
                pen = pg.mkPen(color=self.colors[color_idx], width=2)
                self.residualLines[variable] = self.graphWidget.plot(
                    [], [], name=variable, pen=pen
                )

            while len(self.residualData[variable]) < len(self.timeData) - 1:
                self.residualData[variable].append(None)

            self.residualData[variable].append(residual)

            self.updateResidualPlot(variable)

        # Captura max(cloud:alpha)
        max_alpha_match = re.search(r'Max cell volume fraction\s*=\s*([0-9.eE+-]+)', line)
        if max_alpha_match:
            value = float(max_alpha_match.group(1))
            # Garante que o valor seja associado ao último tempo lido
            if self.timeData:
                # Sincroniza: se já existe valor para este tempo, substitui; senão, adiciona
                if len(self.maxCloudAlphaData) == len(self.timeData):
                    self.maxCloudAlphaData[-1] = value
                elif len(self.maxCloudAlphaData) < len(self.timeData):
                    # Preenche com None se necessário
                    while len(self.maxCloudAlphaData) < len(self.timeData) - 1:
                        self.maxCloudAlphaData.append(None)
                    self.maxCloudAlphaData.append(value)
                else:
                    # Caso raro: mais maxCloudAlpha do que timeData
                    self.maxCloudAlphaData = self.maxCloudAlphaData[:len(self.timeData)-1] + [value]
                self.updateMaxCloudAlphaPlot()

    def updateResidualPlot(self, variable):
        """
        Atualiza o gráfico de resíduos para uma variável específica.
        """
        if variable in self.residualLines:
            filtered_time_data = [t for t, r in zip(self.timeData, self.residualData[variable]) if r is not None]
            filtered_residual_data = [r for r in self.residualData[variable] if r is not None]

            if filtered_time_data and filtered_residual_data:
                self.residualLines[variable].setData(filtered_time_data, filtered_residual_data)

    def updateMaxCloudAlphaPlot(self):
        # Cria a linha se não existir
        if self.maxCloudAlphaLine is None:
            pen = pg.mkPen(color='r', width=2, style=Qt.DashLine)
            self.maxCloudAlphaLine = self.graphWidget.plot([], [], name='max(cloud:alpha)', pen=pen)
        # Plota apenas os pontos válidos
        times = [t for t, v in zip(self.timeData, self.maxCloudAlphaData) if v is not None]
        values = [v for v in self.maxCloudAlphaData if v is not None]
        self.maxCloudAlphaLine.setData(times, values)

    def clearResidualPlot(self):
        self.timeData = []
        self.residualData = {}
        self.graphWidget.clear()
        self.residualLines = {}
        self.maxCloudAlphaData = []
        self.maxCloudAlphaLine = None

    def connectProcessSignals(self, process):
        """
        Conecta os sinais do processo para capturar saída e atualizar resíduos.
        """
        def readOutput():
            while process.canReadLine():
                line = process.readLine().data().decode("utf-8").strip()
                self.outputArea.append(line)  
                self.parseResiduals(line)    

        def readError():
            while process.canReadLine():
                line = process.readLine().data().decode("utf-8").strip()
                self.outputArea.append(f"Erro: {line}")

        process.readyReadStandardOutput.connect(readOutput)
        process.readyReadStandardError.connect(readError)

        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.outputArea.append("Iniciando simulação...")
        
        if not self.unvFilePath:
            self.outputArea.append("Erro: Nenhum caso selecionado")
            return

        required_dirs = ["0", "system", "constant"]
        if not all(QDir(self.unvFilePath).exists(dir_name) for dir_name in required_dirs):
            self.outputArea.append("Erro: A pasta selecionada não contém os diretórios necessários (0, system, constant).")
            return

        if not self.currentSolver:
            self.outputArea.append("Erro: Nenhum solver selecionado")
            return

        self.clearResidualPlot()

        command = f'bash -l -c "source /opt/{self.currentOpenFOAMVersion}/etc/bashrc && mpirun -np 6 {self.currentSolver} -parallel"'

        self.outputArea.append(f"Iniciando simulação com {self.currentSolver}...")
        self.currentProcess = QProcess(self)
        self.setupProcessEnvironment(self.currentProcess)

        def finished(code):
            if code == 0:
                self.outputArea.append("Simulação concluída com sucesso.")
            else:
                self.outputArea.append(f"Simulação finalizada com código de erro: {code}")

        self.currentProcess.finished.connect(finished)
        self.connectProcessSignals(self.currentProcess)
        self.outputArea.append(f"Comando executado: {command}")

        self.currentProcess.start("bash", ["-l", "-c", command])
        self.currentProcess.finished.connect(lambda: self.logSimulationCompletion(start_time))

    def logSimulationCompletion(self, start_time):
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "Finished" if self.currentProcess.exitCode() == 0 else "Interrupted"
        self.simulationHistory.add_entry(
            solver=self.currentSolver,
            case_path=self.unvFilePath,
            start_time=start_time,
            end_time=end_time,
            status=status
        )
        self.outputArea.append(f"Simulation {status}.")

    def reconstructPar(self):
        if not self.unvFilePath:
            self.outputArea.append("Error: No case selected.")
            return
        
        self.outputArea.append("Reconstruindo caso...")
        command = f'bash -l -c "source /opt/{self.currentOpenFOAMVersion}/etc/bashrc && reconstructPar"'
        
        self.currentProcess = QProcess(self)
        self.setupProcessEnvironment(self.currentProcess)
        self.currentProcess.setWorkingDirectory(self.baseDir)
        
        def finished(code):
            self.outputArea.append(f"Reconstrução finalizada com código {code}", 5000)
            self.currentProcess = None
        
        self.currentProcess.finished.connect(finished)
        self.connectProcessSignals(self.currentProcess)
        self.outputArea.append(f"Command: {command}")
        self.currentProcess.start(command)
    
    def decomposePar(self):
        if not self.unvFilePath:
            self.outputArea.append("Error: No case selected.")
            return

        required_dirs = ["0", "system", "constant"]
        if not all(QDir(self.unvFilePath).exists(dir_name) for dir_name in required_dirs):
            self.outputArea.append("Error: The selected folder does not contain the required directories (0, system, constant).")
            return

        self.outputArea.append("Starting decomposition...")
        command = f'source /opt/{self.currentOpenFOAMVersion}/etc/bashrc && decomposePar'

        self.currentProcess = QProcess(self)
        self.setupProcessEnvironment(self.currentProcess)
        self.currentProcess.setWorkingDirectory(self.baseDir)

        def finished(code):
            if code == 0:
                self.outputArea.append("Decomposition completed successfully.")
            else:
                self.outputArea.append(f"Decomposition finished with error code: {code}")

        self.currentProcess.finished.connect(finished)
        self.connectProcessSignals(self.currentProcess)
        self.currentProcess.start("bash", ["-c", command])
    
    def clearSimulation(self):
        caseDir = QDir(self.baseDir)
        timeDirs = caseDir.entryList(QDir.Dirs | QDir.NoDotAndDotDot)
        removedAny = False
        
        for dirName in timeDirs:
            try:
                timeValue = float(dirName)
                if timeValue > 0:
                    timeDir = QDir(caseDir.filePath(dirName))
                    if timeDir.removeRecursively():
                        self.outputArea.append(f"Removed time folder: {dirName}")
                        removedAny = True
            except ValueError:
                pass
        
        if removedAny:
            self.outputArea.append("Time folders removed successfully.")
        else:
            self.outputArea.append("No time folders found to remove.")

    def runSimulation(self):
        """Inicia a simulação após perguntar o tempo de execução e atualizar o controlDict."""
        if self.currentProcess and self.currentProcess.state() == QProcess.Running:
            self.outputArea.append("Outra simulação já está em execução. Pare-a antes de iniciar uma nova.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Tempo de Simulação")
        layout = QVBoxLayout(dialog)
        label = QLabel("Informe o tempo final da simulação (endTime):", dialog)
        timeInput = QLineEdit(dialog)
        timeInput.setPlaceholderText("Exemplo: 10 (deixe em branco para padrão)")
        okButton = QPushButton("OK", dialog)
        cancelButton = QPushButton("Cancelar", dialog)
        buttonLayout = QHBoxLayout()
        buttonLayout.addWidget(okButton)
        buttonLayout.addWidget(cancelButton)
        layout.addWidget(label)
        layout.addWidget(timeInput)
        layout.addLayout(buttonLayout)
        dialog.setLayout(layout)

        def on_ok():
            dialog.accept()
        def on_cancel():
            dialog.reject()
        okButton.clicked.connect(on_ok)
        cancelButton.clicked.connect(on_cancel)

        if not dialog.exec_():
            self.outputArea.append("Execução da simulação cancelada pelo usuário.")
            return

        user_end_time = timeInput.text().strip()

        import os
        controlDict_path = os.path.join(self.baseDir, "system", "controlDict")
        if not os.path.exists(controlDict_path):
            self.outputArea.append("Erro: controlDict não encontrado.")
            return

        try:
            with open(controlDict_path, "r") as f:
                lines = f.readlines()

            new_lines = []
            for line in lines:
                if line.strip().startswith("endTime") and user_end_time:
                    new_lines.append(f"endTime         {user_end_time};\n")
                else:
                    new_lines.append(line)

            with open(controlDict_path, "w") as f:
                f.writelines(new_lines)

            self.outputArea.append("Arquivo controlDict atualizado com novo endTime.")
        except Exception as e:
            self.outputArea.append(f"Erro ao atualizar controlDict: {e}")
            return

        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.outputArea.append("Iniciando simulação...")

        if not self.unvFilePath:
            self.outputArea.append("Erro: Nenhum caso selecionado.")
            return

        caseDir = self.baseDir
        allrunPath = os.path.join(caseDir, "Allrunparallel")
        if not os.path.exists(allrunPath):
            self.outputArea.append("Erro: Script Allrunparallel não encontrado.")
            return

        if not os.access(allrunPath, os.X_OK):
            os.chmod(allrunPath, 0o755)

        command = f'source /opt/{self.currentOpenFOAMVersion}/etc/bashrc && cd {caseDir} && ./Allrunparallel'
        self.currentProcess = QProcess(self)
        self.setupProcessEnvironment(self.currentProcess)
        self.currentProcess.setWorkingDirectory(caseDir)

        def finished(code):
            if code == 0:
                self.outputArea.append("Simulação finalizada com sucesso.")
            else:
                self.outputArea.append(f"Simulação finalizada com erro: {code}")
            self.logSimulationCompletion(start_time)

        self.currentProcess.finished.connect(finished)
        self.connectProcessSignals(self.currentProcess)
        self.currentProcess.start("bash", ["-c", command])
    
    def pauseSimulation(self):
        """Pausa a simulação em execução enviando o sinal SIGSTOP para todos os processos filhos."""
        if self.currentProcess and self.currentProcess.state() == QProcess.Running:
            pid = self.currentProcess.processId()
            if pid:
                try:
                    import psutil
                    parent = psutil.Process(pid)
                    # Pausa todos os filhos recursivamente
                    for child in parent.children(recursive=True):
                        child.suspend()
                    parent.suspend()
                    self.outputArea.append("Simulação pausada (todos os processos).")
                except Exception as e:
                    self.outputArea.append(f"Erro ao pausar a simulação: {e}")
            else:
                self.outputArea.append("Não foi possível obter o PID do processo para pausar.")
        else:
            self.outputArea.append("Nenhuma simulação em execução para pausar.")

    def resumeSimulation(self):
        """Retoma uma simulação pausada enviando o sinal SIGCONT para todos os processos filhos."""
        if self.currentProcess:
            pid = self.currentProcess.processId()
            if pid:
                try:
                    import psutil
                    parent = psutil.Process(pid)
                    # Retoma todos os filhos recursivamente
                    for child in parent.children(recursive=True):
                        child.resume()
                    parent.resume()
                    self.outputArea.append("Simulação retomada (todos os processos).")
                except Exception as e:
                    self.outputArea.append(f"Erro ao retomar a simulação: {e}")
            else:
                self.outputArea.append("Não foi possível obter o PID do processo para retomar.")
        else:
            self.outputArea.append("Nenhuma simulação para retomar.")

    def restartSimulation(self):
        """Reinicia a simulação."""
        # First, stop any existing simulation
        if self.currentProcess and self.currentProcess.state() == QProcess.Running:
            self.stopSimulation() # Ensure it's fully stopped
            # Wait a bit for the process to terminate if stopSimulation is asynchronous in effect
            # Or ensure stopSimulation is blocking or provides a callback/signal
            # For simplicity here, we assume stopSimulation effectively stops it before proceeding.

        # Clear necessary previous run data, e.g., processor directories, logs if needed
        # self.clearDecomposedProcessors() # Example, if you always want to clear these
        # self.clearOldProcessorDirs() # As per your existing method

        self.outputArea.append("Reiniciando a simulação...")
        # Re-run the simulation. This might be similar to runSimulation or a specific restart logic
        self.runSimulation() # Assuming runSimulation can handle starting fresh or from where it should

    def clearDecomposedProcessors(self):
        if not self.baseDir: 
            self.outputArea.append("Erro: Nenhum diretório base selecionado.")
            return

        caseDir = QDir(self.baseDir)
        processorDirs = caseDir.entryList(["processor*"], QDir.Dirs | QDir.NoDotAndDotDot)
        removedAny = False

        for dirName in processorDirs:
            processorDir = QDir(caseDir.filePath(dirName))
            if processorDir.removeRecursively():
                self.outputArea.append(f"Removendo pasta: {dirName}")
                removedAny = True

        if removedAny:
            self.outputArea.append("Pastas de decomposição removidas com sucesso.")
        else:
            self.outputArea.append("Nenhuma pasta de decomposição encontrada.")
    
    def stopSimulation(self):
        """Para o processo de simulação em execução e seus processos filhos."""
        if self.currentProcess and self.currentProcess.state() == QProcess.Running:
            self.outputArea.append("Parando a simulação...")
            
            pid = self.currentProcess.processId()
            
            try:
                parent = psutil.Process(pid)
                for child in parent.children(recursive=True): 
                    child.terminate()  
                parent.terminate()  
                gone, still_alive = psutil.wait_procs(parent.children(recursive=True), timeout=5)
                for p in still_alive:
                    p.kill()  
                parent.kill()
                self.outputArea.append("Simulação interrompida com sucesso.")
            except psutil.NoSuchProcess:
                self.outputArea.append("O processo já foi encerrado.")
            except Exception as e:
                self.outputArea.append(f"Erro ao encerrar o processo: {e}")
            
            from datetime import datetime
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            start_time = end_time  
            self.simulationHistory.add_entry(
                solver=self.currentSolver,
                case_path=self.unvFilePath,
                start_time=start_time,
                end_time=end_time,
                status="Interrompida"
            )
            self.outputArea.append("Simulação Interrompida.")
            
            self.currentProcess = None 
        else:
            self.outputArea.append("Nenhuma simulação em execução para parar.")

    def clearTerminal(self):
        self.outputArea.clear()
        self.outputArea.append("Terminal limpo.", 2000)

    def enableProfiling(self):
        import os
        # Verifica se o diretório base está selecionado e é válido
        if not self.baseDir or not os.path.isdir(self.baseDir):
            self.outputArea.append("Erro: Nenhum diretório base selecionado.")
            return
        required_dirs = ["0", "constant", "system"]
        if not all(os.path.isdir(os.path.join(self.baseDir, d)) for d in required_dirs):
            self.outputArea.append("Erro: O diretório base selecionado não contém as pastas 0, constant e system.")
            return
        controlDict_path = os.path.join(self.baseDir, "system", "controlDict")
        if not os.path.exists(controlDict_path):
            self.outputArea.append(f"Erro: controlDict não encontrado em {controlDict_path}.")
            return
        try:
            with open(controlDict_path, "r") as f:
                lines = f.readlines()
            
            # Remove blocos InfoSwitches e DebugSwitches existentes, se houver
            new_lines = []
            inside_info = False
            inside_debug = False
            
            for line in lines:
                if 'InfoSwitches' in line:
                    inside_info = True
                    continue
                elif 'DebugSwitches' in line:
                    inside_debug = True
                    continue
                
                if inside_info or inside_debug:
                    if '}' in line:
                        inside_info = False
                        inside_debug = False
                    continue
                
                new_lines.append(line)
            
            # Adiciona blocos InfoSwitches e DebugSwitches antes do final do arquivo
            insert_idx = len(new_lines)
            for i, line in enumerate(reversed(new_lines)):
                if '*****' in line:
                    insert_idx = len(new_lines) - i - 1
                    break
            
            # Adiciona InfoSwitches
            new_lines.insert(insert_idx, 'InfoSwitches\n')
            new_lines.insert(insert_idx+1, '{\n')
            new_lines.insert(insert_idx+2, '    time 1;\n')
            new_lines.insert(insert_idx+3, '}\n')
            new_lines.insert(insert_idx+4, '\n')
            
            # Adiciona DebugSwitches
            new_lines.insert(insert_idx+5, 'DebugSwitches\n')
            new_lines.insert(insert_idx+6, '{\n')
            new_lines.insert(insert_idx+7, '    // 0 = off, 1 = on\n')
            new_lines.insert(insert_idx+8, '    InfoSwitch          1;\n')
            new_lines.insert(insert_idx+9, '    TimeRegistry        1;  // Esta é a chave! Garante profiling detalhado.\n')
            new_lines.insert(insert_idx+10, '}\n')
            
            with open(controlDict_path, "w") as f:
                f.writelines(new_lines)
            
            self.outputArea.append("Profiling completo ativado no controlDict!")
            self.outputArea.append("- InfoSwitches { time 1; } adicionado")
            self.outputArea.append("- DebugSwitches { TimeRegistry 1; } adicionado")
            self.profilingLogs.append("Profiling detalhado ativado - TimeRegistry habilitado!")
            
        except Exception as e:
            self.outputArea.append(f"Erro ao ativar profiling: {e}")
    
    def editFile(self):
        """Abre um arquivo para edição no editor."""
        fileName, _ = QFileDialog.getOpenFileName(
            self,
            "Escolher Arquivo de Código",
            self.systemDir,
            "Todos os Arquivos (*);;Arquivos de Código (*.dict *.txt *.swp)"
        )
        if fileName:
            file = QtCore.QFile(fileName)
            if file.open(QtCore.QIODevice.ReadOnly | QtCore.QIODevice.Text):
                self.currentFilePath = fileName
                self.fileEditor.setPlainText(str(file.readAll(), 'utf-8'))
                file.close()
                self.outputArea.append(f"Arquivo de código aberto: {fileName}")
            else:
                self.outputArea.append("Erro ao abrir o arquivo para edição.")
        else:
            self.outputArea.append("Nenhum arquivo selecionado.")
    
    def saveFile(self):
        if not self.currentFilePath:
            self.outputArea.append("Nenhum arquivo carregado para salvar.")
            return
        
        file = QtCore.QFile(self.currentFilePath)
        if file.open(QtCore.QIODevice.WriteOnly | QtCore.QIODevice.Text):
            file.write(self.fileEditor.toPlainText().encode('utf-8'))
            file.close()
            self.outputArea.append(f"Arquivo salvo com sucesso: {self.currentFilePath}")
        else:
            self.outputArea.append("Erro ao salvar o arquivo.")
    
    def executeTerminalCommand(self):
        command = self.terminalInput.text()
        if command:
            self.outputArea.append(f"> {command}")
            self.terminalInput.clear()
            
            process = QProcess(self)
            self.setupProcessEnvironment(process)
            self.connectProcessSignals(process)
            
            process.setWorkingDirectory(self.baseDir)
            
            fullCommand = f'source /opt/{self.currentOpenFOAMVersion}/etc/bashrc && {command}'
            process.start("bash", ["-l", "-c", fullCommand])
            
            firstWord = command.split(' ')[0]
            self.outputArea.append(f"Comando executado: {firstWord}", 2000)
            
    
    def setupProcessEnvironment(self, process):
        env = QProcessEnvironment.systemEnvironment()
        foam_dir = f"/opt/{self.currentOpenFOAMVersion}"
        env.insert("FOAM_RUN", foam_dir)
        env.insert("LD_LIBRARY_PATH", f"{foam_dir}/lib:{foam_dir}/platforms/linux64GccDPInt32Opt/lib")
        process.setProcessEnvironment(env)
    
    def connectProcessSignals(self, process):
        """Conecta os sinais do processo para capturar saída e atualizar resíduos."""
        def readOutput():
            while process.canReadLine():
                output = str(process.readLine(), 'utf-8').strip()
                self.outputArea.append(output)
                self.parseResiduals(output)
                QApplication.processEvents() 

        def readError():
            error = str(process.readAllStandardError(), 'utf-8').strip()  
            self.outputArea.append(error)

        process.readyReadStandardOutput.connect(readOutput)
        process.readyReadStandardError.connect(readError)


    def calculateRates(self):
        try:
            d = 0.106
            n = 30
            m = 10
            dy_in_0 = 0.00142
            dy_wall_0 = 0.008

            results = calculate_increase_rate(d, n, m, dy_in_0, dy_wall_0)

            self.outputArea.append("Resultados do cálculo de Δy")
            for key, value in results.items():
                self.outputArea.append(f"{key}: {value:.5f}" if isinstance(value, float) else f"{key}: {value}")
        except Exception as e:
            self.outputArea.append(f"Erro ao calcular taxas: {str(e)}")

    def openRateCalculationDialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Calcular Δy")
        dialog.setModal(True)
        dialog.resize(350, 250)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #2c3e50;
                border: 2px solid #3498db;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(dialog)

        # Styling for labels in dialog
        label_style = """
            QLabel {
                color: #ecf0f1;
                font-weight: bold;
                font-size: 12px;
                padding: 5px;
            }
        """
        
        # Styling for input fields in dialog
        input_style = """
            QLineEdit {
                background-color: #34495e;
                color: white;
                border: 1px solid #3498db;
                border-radius: 4px;
                padding: 8px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border-color: #2ecc71;
                background-color: #3c4f66;
            }
        """

        dLabel = QLabel("d (diâmetro):", dialog)
        dLabel.setStyleSheet(label_style)
        dInput = QLineEdit(dialog)
        dInput.setStyleSheet(input_style)
        dInput.setPlaceholderText("Exemplo: 0.106")

        nLabel = QLabel("n (distância do bocal):", dialog)
        nLabel.setStyleSheet(label_style)
        nInput = QLineEdit(dialog)
        nInput.setStyleSheet(input_style)
        nInput.setPlaceholderText("Exemplo: 30")

        mLabel = QLabel("m (distância de transição):", dialog)
        mLabel.setStyleSheet(label_style)
        mInput = QLineEdit(dialog)
        mInput.setStyleSheet(input_style)
        mInput.setPlaceholderText("Exemplo: 10")

        dyIn0Label = QLabel("dy_in_0 (altura inicial):", dialog)
        dyIn0Label.setStyleSheet(label_style)
        dyIn0Input = QLineEdit(dialog)
        dyIn0Input.setStyleSheet(input_style)
        dyIn0Input.setPlaceholderText("Exemplo: 0.00142")

        dyWall0Label = QLabel("dy_wall_0 (altura na parede):", dialog)
        dyWall0Label.setStyleSheet(label_style)
        dyWall0Input = QLineEdit(dialog)
        dyWall0Input.setStyleSheet(input_style)
        dyWall0Input.setPlaceholderText("Exemplo: 0.008")

        calculateButton = QPushButton("Calcular", dialog)
        calculateButton.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
            QPushButton:pressed {
                background-color: #229954;
            }
        """)
        calculateButton.clicked.connect(lambda: self.calculateRatesFromDialog(
            dialog, dInput.text(), nInput.text(), mInput.text(), dyIn0Input.text(), dyWall0Input.text()
        ))

        layout.addWidget(dLabel)
        layout.addWidget(dInput)
        layout.addWidget(nLabel)
        layout.addWidget(nInput)
        layout.addWidget(mLabel)
        layout.addWidget(mInput)
        layout.addWidget(dyIn0Label)
        layout.addWidget(dyIn0Input)
        layout.addWidget(dyWall0Label)
        layout.addWidget(dyWall0Input)
        layout.addWidget(calculateButton)

        dialog.exec_()

    def calculateRatesFromDialog(self, dialog, d, n, m, dy_in_0, dy_wall_0):
        try:
            
            d = float(d)
            n = float(n)
            m = float(m)
            dy_in_0 = float(dy_in_0)
            dy_wall_0 = float(dy_wall_0)

            results = calculate_increase_rate(d, n, m, dy_in_0, dy_wall_0)

            self.outputArea.append("Resultados do cálculo de Δy")
            for key, value in results.items():
                self.outputArea.append(f"{key}: {value:.5f}" if isinstance(value, float) else f"{key}: {value}")

            dialog.accept()
        except ValueError:
            self.outputArea.append("Erro: Certifique-se de que todos os valores são números válidos.")
        except Exception as e:
            self.outputArea.append(f"Erro ao calcular taxas: {str(e)}")

    def openFluidPropertiesDialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Calcular Propriedades do Fluido")
        dialog.setModal(True)
        dialog.resize(300, 300)

        layout = QVBoxLayout(dialog)

        tempLabel = QLabel("Temperatura (°C):", dialog)
        tempInput = QLineEdit(dialog)
        tempInput.setPlaceholderText("Exemplo: 46.6")

        pressureLabel = QLabel("Pressão (MPa):", dialog)
        pressureInput = QLineEdit(dialog)
        pressureInput.setPlaceholderText("Exemplo: 9.64")

        salinityLabel = QLabel("Salinidade (mg/L):", dialog)
        salinityInput = QLineEdit(dialog)
        salinityInput.setPlaceholderText("Exemplo: 323000")

        calculateButton = QPushButton("Calcular", dialog)
        calculateButton.clicked.connect(lambda: self.calculateFluidProperties(
            dialog, tempInput.text(), pressureInput.text(), salinityInput.text()
        ))

        layout.addWidget(tempLabel)
        layout.addWidget(tempInput)
        layout.addWidget(pressureLabel)
        layout.addWidget(pressureInput)
        layout.addWidget(salinityLabel)
        layout.addWidget(salinityInput)
        layout.addWidget(calculateButton)

        dialog.exec_()

    def calculateFluidProperties(self, dialog, temp, pressure, salinity):
        try:
            temp = float(temp)
            pressure = float(pressure) * 10  # Converte MPa para bar
            salinity = float(salinity) / 1e6  # Converte mg/L para fração mássica

            fluid = FluidProperties()

            density = fluid.brine_density(temp, pressure, salinity)
            viscosity = fluid.brine_viscosity(temp, pressure, salinity) * 1000  # Converte Pa.s para mPa.s

            self.outputArea.append("Resultados das Propriedades do Fluido:")
            self.outputArea.append(f"Temperatura: {temp} °C")
            self.outputArea.append(f"Pressão: {pressure} bar")
            self.outputArea.append(f"Salinidade: {salinity:.6f} (fração mássica)")
            self.outputArea.append(f"Densidade: {density:.2f} kg/m³")
            self.outputArea.append(f"Viscosidade: {viscosity:.6f} mPa·s")

            dialog.accept()
        except ValueError:
            self.outputArea.append("Erro: Certifique-se de que todos os valores são números válidos.")
        except Exception as e:
            self.outputArea.append(f"Erro ao calcular propriedades: {str(e)}")

    def openSimulationHistory(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Histórico de Simulações")
        dialog.resize(800, 400)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #2c3e50;
                border: 2px solid #3498db;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(dialog)

        self.historyTable = QTableWidget(dialog)
        self.historyTable.setStyleSheet("""
            QTableWidget {
                background-color: #34495e;
                color: white;
                border: 1px solid #3498db;
                border-radius: 4px;
                gridline-color: #3498db;
                selection-background-color: #3498db;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #3498db;
            }
            QTableWidget::item:selected {
                background-color: #3498db;
                color: white;
            }
            QHeaderView::section {
                background-color: #2c3e50;
                color: white;
                padding: 10px;
                border: 1px solid #3498db;
                font-weight: bold;
            }
        """)
        self.historyTable.setColumnCount(5)
        self.historyTable.setHorizontalHeaderLabels(["Solver", "Malha", "Início", "Fim", "Status"])
        self.loadHistoryIntoTable()
        layout.addWidget(self.historyTable)

        buttonLayout = QHBoxLayout()
        # Styled buttons for dialog
        button_style = """
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:pressed {
                background-color: #a93226;
            }
        """
        clearAllButton = QPushButton("Limpar Tudo", dialog)
        clearAllButton.setStyleSheet(button_style)
        clearAllButton.clicked.connect(self.clearAllSimulations)
        buttonLayout.addWidget(clearAllButton)

        deleteSelectedButton = QPushButton("Excluir Selecionado", dialog)
        deleteSelectedButton.setStyleSheet(button_style.replace("#e74c3c", "#f39c12").replace("#c0392b", "#e67e22").replace("#a93226", "#d35400"))
        deleteSelectedButton.clicked.connect(self.deleteSelectedSimulation)
        buttonLayout.addWidget(deleteSelectedButton)

        # Botão para ver os últimos logs
        viewLogsButton = QPushButton("Ver Últimos Logs", dialog)
        viewLogsButton.setStyleSheet(button_style.replace("#e74c3c", "#2980b9").replace("#c0392b", "#3498db").replace("#a93226", "#2471a3"))
        viewLogsButton.clicked.connect(self.showSelectedSimulationLogs)
        buttonLayout.addWidget(viewLogsButton)

        layout.addLayout(buttonLayout)
        dialog.setLayout(layout)
        dialog.exec_()

    def showSelectedSimulationLogs(self):
        selectedRow = self.historyTable.currentRow()
        if selectedRow == -1:
            QMessageBox.warning(self, "Nenhuma Seleção", "Por favor, selecione uma simulação para ver os logs.")
            return
        history = self.simulationHistory.get_history()
        if selectedRow >= len(history):
            QMessageBox.warning(self, "Erro", "Índice de simulação inválido.")
            return
        entry = history[selectedRow]
        log_data = entry.get("log_data", [])
        log_text = "\n".join(log_data) if log_data else "Nenhum log relevante encontrado."
        logDialog = QDialog(self)
        logDialog.setWindowTitle("Últimos Logs da Simulação")
        logDialog.resize(700, 400)
        vbox = QVBoxLayout(logDialog)
        logEdit = QTextEdit(logDialog)
        logEdit.setReadOnly(True)
        logEdit.setPlainText(log_text)
        vbox.addWidget(logEdit)
        closeBtn = QPushButton("Fechar", logDialog)
        closeBtn.clicked.connect(logDialog.accept)
        vbox.addWidget(closeBtn)
        logDialog.setLayout(vbox)
        logDialog.exec_()

    def loadHistoryIntoTable(self):
        """Carrega o histórico na tabela."""
        history = self.simulationHistory.get_history()
        self.historyTable.setRowCount(len(history))
        for row, entry in enumerate(history):
            self.historyTable.setItem(row, 0, QTableWidgetItem(entry["solver"]))
            self.historyTable.setItem(row, 1, QTableWidgetItem(entry["case_path"]))
            self.historyTable.setItem(row, 2, QTableWidgetItem(entry["start_time"]))
            self.historyTable.setItem(row, 3, QTableWidgetItem(entry["end_time"]))
            self.historyTable.setItem(row, 4, QTableWidgetItem(entry["status"]))

    def clearAllSimulations(self):
        """Limpa todo o histórico de simulações."""
        reply = QMessageBox.question(
            self, "Confirmação", "Tem certeza de que deseja limpar todo o histórico?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.simulationHistory.history = []
            self.simulationHistory.save_history()
            self.loadHistoryIntoTable()  
            QMessageBox.information(self, "Histórico Limpo", "Todo o histórico foi limpo com sucesso.")

    def deleteSelectedSimulation(self):
        """Exclui a simulação selecionada na tabela."""
        selectedRow = self.historyTable.currentRow()
        if selectedRow == -1:
            QMessageBox.warning(self, "Nenhuma Seleção", "Por favor, selecione uma simulação para excluir.")
            return

        reply = QMessageBox.question(
            self, "Confirmação", "Tem certeza de que deseja excluir a simulação selecionada?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            del self.simulationHistory.history[selectedRow]
            self.simulationHistory.save_history()
            self.loadHistoryIntoTable()
            QMessageBox.information(self, "Simulação Excluída", "A simulação selecionada foi excluída com sucesso.")

    def filterTreeView(self, text):
        """Filtra os itens da árvore de diretórios com base no texto inserido."""
        def filterItems(item, text):
            match = text.lower() in item.text().lower()
            for row in range(item.rowCount()):
                child = item.child(row)
                match = filterItems(child, text) or match
            item.setHidden(match)
            return match

        for row in range(self.treeModel.rowCount()):
            rootItem = self.treeModel.item(row)
            filterItems(rootItem, text)

    def configureDecomposeParCores(self):
        """Abre um diálogo para configurar o número de núcleos e atualiza o decomposeParDict."""
        num_cores, ok = QInputDialog.getInt(
            self,
            "Configurar Núcleos",
            "Digite o número de núcleos para decomposePar:",
            min=1,
            max=128,  
            value=2 
        )
        if ok:
            self.num_cores = num_cores  
            decompose_par_dict_path = os.path.join(self.baseDir, "system", "decomposeParDict")
            try:
                with open(decompose_par_dict_path, "r") as file:
                    lines = file.readlines()

                with open(decompose_par_dict_path, "w") as file:
                    for line in lines:
                        if "numberOfSubdomains" in line:
                            file.write(f"numberOfSubdomains {num_cores};\n")
                        else:
                            file.write(line)

                self.outputArea.append(f"Arquivo decomposeParDict atualizado com {num_cores} núcleos.")

            except FileNotFoundError:
                self.outputArea.append("Erro: Arquivo decomposeParDict não encontrado.")
            except Exception as e:
                self.outputArea.append(f"Erro ao atualizar decomposeParDict: {str(e)}")

    def load_config(self):
        """Carrega as configurações do arquivo config.json."""
        if os.path.exists(self.config_file):
            with open(self.config_file, "r") as file:
                return json.load(file)
        else:
            return {}

    def save_config(self):
        """Salva as configurações no arquivo config.json."""
        with open(self.config_file, "w") as file:
            json.dump(self.config, file, indent=4)

    def set_base_dir(self):
        """Permite ao usuário definir o diretório base."""
        new_base_dir = QFileDialog.getExistingDirectory(
            self, "Escolher Diretório Base", 
            self.baseDir, 
            QFileDialog.ShowDirsOnly
        )
        if new_base_dir: 
            self.baseDir = new_base_dir
            self.systemDir = os.path.join(self.baseDir, "system")
            self.config["baseDir"] = self.baseDir
            self.save_config()
            self.outputArea.append(f"Diretório base configurado para: {self.baseDir}")
            
            # self.populateTreeView(self.baseDir)
        else:
            self.outputArea.append("Nenhum diretório base selecionado.")

    def showSimulationLogs(self):
        """Exibe os logs da simulação em tempo real."""
        if not self.baseDir or not os.path.exists(self.baseDir):
            self.outputArea.append("Erro: Nenhum caso selecionado ou diretório base inválido.")
            return

        logFilePath = os.path.join(self.baseDir, "log.foamRun")
        if not os.path.exists(logFilePath):
            self.outputArea.append(f"Erro: Arquivo de log não encontrado em {logFilePath}.")
            return

        self.outputArea.append("Exibindo logs em tempo real...")
        command = f"tail -f {logFilePath}"

        self.logProcess = QProcess(self)
        self.logProcess.setProcessChannelMode(QProcess.MergedChannels)
        self.logProcess.readyReadStandardOutput.connect(self.readLogOutput)
        self.logProcess.finished.connect(self.logProcessFinished)

        self.logProcess.start("bash", ["-c", command])

    def readLogOutput(self):
        """Lê a saída do processo de logs e exibe na área de saída."""
        if self.logProcess:
            output = str(self.logProcess.readAllStandardOutput(), 'utf-8').strip()
            lines = output.split("\n") 
            for line in lines:
                self.outputArea.append(line) 
                self.parseResiduals(line)  

    def logProcessFinished(self):
        """Notifica quando o processo de logs é finalizado."""
        self.outputArea.append("Exibição de logs finalizada.")
        self.logProcess = None

    def closeEvent(self, event):
        """Intercepta o evento de fechamento da janela para encerrar processos em execução."""
        if self.currentProcess and self.currentProcess.state() == QProcess.Running:
            self.currentProcess.terminate()
            if not self.currentProcess.waitForFinished(3000):  
                self.currentProcess.kill() 
            self.outputArea.append("Simulação interrompida ao fechar o programa.")
        
        if self.logProcess and self.logProcess.state() == QProcess.Running:
            self.logProcess.terminate()
            if not self.logProcess.waitForFinished(3000):
                self.logProcess.kill()
            self.outputArea.append("Processo de logs interrompido ao fechar o programa.")
        
        event.accept()  

    def showSimulationInfo(self):
        info_text = (
            "Com o tempo, este valor aumentou significativamente, chegando a ~0.739836.\n\n"
            "Isso significa que em pelo menos uma célula do domínio, cerca de 74% do volume está ocupado por partículas. "
            "Isso indica uma região de alta concentração, o que pode ser indicativo de aglomeração ou sedimentação das partículas.\n\n"
            "O que isso pode indicar fisicamente?\n"
            "O aumento expressivo de max(cloud:alpha) pode indicar:\n\n"
            "- Formação de uma zona de acúmulo de partículas (sedimentação ou aglomeração local).\n"
            "- Baixa dispersão devido a características do escoamento ou forças de interação entre partículas.\n"
            "- Restrição de escoamento em regiões densamente povoadas por partículas.\n\n"
            "🔧 Considerações numéricas\n"
            "Apesar do aumento da fração volumétrica de partículas, o solver continua convergindo (Final residual < 1e-6), o que é bom.\n\n"
            "Porém, valores muito altos de alpha (>0.6) podem causar problemas de estabilidade ou de interpretação física, "
            "especialmente se o modelo assumir regime diluído (por exemplo, se estiver usando o modelo kinematicCloud, que assume interação fraca entre partículas).\n\n"
            "Se estiver usando um modelo denso (denseParticleFoam ou similar), é esperado que alpha seja mais alto, mas precisa garantir que está dentro dos limites físicos e consistentes com o modelo de interação partícula-partícula."
        )
        dialog = QDialog(self)
        dialog.setWindowTitle("Informações da Simulação")
        dialog.resize(600, 400)
        layout = QVBoxLayout(dialog)
        label = QLabel(info_text, dialog)
        label.setWordWrap(True)
        layout.addWidget(label)
        closeButton = QPushButton("Fechar", dialog)
        closeButton.clicked.connect(dialog.accept)
        layout.addWidget(closeButton)
        dialog.setLayout(layout)
        dialog.exec_()
        
class FluidProperties:
    def __init__(self):
        self.c0, self.c1, self.c2, self.c3 = (999.842594, 0.06793952, -0.00909529, 0.0001001685) # Example values
        self.A, self.B = (0.0004831439, 0.000001617e-05) # Example values
        self.mu_c_800 = 2.0  
        self.mu_w_base = 0.00089  

    def water_density(self, T, P):
        """Calcula a densidade da água pura (rho_w) em função da temperatura (T) e pressão (P)."""
        rho_0 = self.c0 + self.c1 * T + self.c2 * T**2 + self.c3 * T**3
        rho_w = rho_0 + self.A * P + self.B * P**2
        return rho_w

    def brine_density(self, T, P, X):
        """Calcula a densidade da salmoura (rho_b) em função de T, P e salinidade (X)."""
        rho_w_TP = self.water_density(T, P)
        rho_b = rho_w_TP + X * (1695 - rho_w_TP)
        return rho_b

    def brine_viscosity(self, T, P, X):
        """Calcula a viscosidade da salmoura (mu_b) em função de T, P e salinidade (X)."""
        if T < 800:
            term1 = self.mu_w_base * (1 + 3 * X) * ((800 - T) / 800) ** 9
            term2 = ((T / 800) ** 9) * (self.mu_w_base * (1 - X) + X * self.mu_c_800)
            mu_b = (term1 + term2) / (((800 - T) / 800) ** 9 + (T / 800) ** 9)
        else:
            mu_b = self.mu_w_base * (1 - X) + self.mu_c_800 * X
        return mu_b

class FileEditorWindow(QDialog):
    def __init__(self, baseDir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("File Editor")
        self.resize(800, 600)
        self.setModal(True)  

        self.baseDir = baseDir
        self.currentFilePath = ""

        layout = QVBoxLayout(self)

        # self.searchBar = QLineEdit(self)
        # self.searchBar.setPlaceholderText("Search files...")
        # layout.addWidget(self.searchBar)

        # self.treeView = QTreeView(self)
        # self.treeModel = QStandardItemModel(self)
        # self.treeView.setModel(self.treeModel)
        # self.treeView.setHeaderHidden(True)
        # self.treeView.doubleClicked.connect(self.onTreeViewDoubleClicked)
        # layout.addWidget(self.treeView)

        self.fileEditor = QTextEdit(self)
        layout.addWidget(self.fileEditor)

        buttonLayout = QHBoxLayout()
        self.saveButton = QPushButton("Save File", self)
        self.saveButton.clicked.connect(self.saveFile)
        buttonLayout.addWidget(self.saveButton)

        self.closeButton = QPushButton("Close", self)
        self.closeButton.clicked.connect(self.close)
        buttonLayout.addWidget(self.closeButton)

        layout.addLayout(buttonLayout)

        # self.populateTreeView(self.baseDir)

    def populateTreeView(self, casePath):
        pass
    def addDirectoryToTree(self, path, parent):
        pass
    def filterTreeView(self, text):
        pass
    def onTreeViewDoubleClicked(self, index):
        pass

    def saveFile(self):
        if not self.currentFilePath:
            QMessageBox.warning(self, "Error", "No file loaded to save.")
            return

        file = QtCore.QFile(self.currentFilePath)
        if file.open(QtCore.QIODevice.WriteOnly | QtCore.QIODevice.Text):
            file.write(self.fileEditor.toPlainText().encode('utf-8'))
            file.close()
            QMessageBox.information(self, "Success", f"File saved: {self.currentFilePath}")
        else:
            QMessageBox.warning(self, "Error", "Failed to save the file.")

def openFileEditor(self):
    """Abre a janela separada para o editor de arquivos."""
    self.fileEditorWindow = FileEditorWindow(self.baseDir, self)
    self.fileEditorWindow.show()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    interface = OpenFOAMInterface()
    interface.show()
    
    sys.exit(app.exec_())
