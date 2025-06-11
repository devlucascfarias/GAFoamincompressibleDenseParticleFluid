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
        
        fileMenu = QMenu("File", self.menuBar)
        
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
        
        === CONTENT AREA (LEFT) ===
        
        '''

        leftContentLayout = QVBoxLayout()
        terminalLayout = QVBoxLayout()
        terminalLayout.addWidget(QLabel("Terminal and Logs", self))
        
        self.openParaviewButton = QPushButton("Open in ParaView", self)
        self.openParaviewButton.clicked.connect(self.openParaview)

        self.calculateRateButton = QPushButton("Calculate Δy", self)
        self.calculateRateButton.clicked.connect(self.openRateCalculationDialog)

        self.fluidPropertiesButton = QPushButton("Calculate Fluid Properties", self)
        self.fluidPropertiesButton.clicked.connect(self.openFluidPropertiesDialog)

        # self.openFileEditorButton = QPushButton("Open File Editor", self)
        # self.openFileEditorButton.clicked.connect(self.openFileEditor)

        buttonRowLayout = QHBoxLayout()
        buttonRowLayout.addWidget(self.openParaviewButton)
        buttonRowLayout.addWidget(self.calculateRateButton)
        buttonRowLayout.addWidget(self.fluidPropertiesButton)
        # buttonRowLayout.addWidget(self.openFileEditorButton)

        self.setCoresButton = QPushButton("Set Cores for decomposePar", self)
        self.setCoresButton.clicked.connect(self.configureDecomposeParCores)
        buttonRowLayout.addWidget(self.setCoresButton)

        # Botão Info da Simulação
        # self.simInfoButton = QPushButton("Info da Simulação", self)
        # self.simInfoButton.clicked.connect(self.showSimulationInfo)
        # buttonRowLayout.addWidget(self.simInfoButton)

        terminalLayout.addLayout(buttonRowLayout)
        
        self.outputArea = QTextEdit(self)
        self.outputArea.setReadOnly(True)
        terminalLayout.addWidget(self.outputArea)
        
        self.terminalInput = QLineEdit(self)
        self.terminalInput.setPlaceholderText(">>")
        self.terminalInput.returnPressed.connect(self.executeTerminalCommand)
        terminalLayout.addWidget(self.terminalInput)
        
        leftContentLayout.addLayout(terminalLayout)
        
        ''' 
        
        === RESIDUAL PLOT ===
        
        '''        
        residualLayout = QVBoxLayout()
        residualLayout.addWidget(QLabel("Residual Plot", self))
        
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
        self.clearPlotButton.clicked.connect(self.clearResidualPlot)

        self.exportPlotDataButton = QPushButton("Export Data", self)
        self.exportPlotDataButton.clicked.connect(self.exportPlotData)  

        graphControlLayout.addWidget(self.clearPlotButton)
        graphControlLayout.addWidget(self.exportPlotDataButton)


        residualLayout.addLayout(graphControlLayout)
        
        leftContentLayout.addLayout(residualLayout)
        
        ''' 
        
        === BUTTON AREA ===
        
        '''

        buttonLayout = QVBoxLayout()
        
        self.convertButton = QPushButton("Convert Mesh", self)
        self.convertButton.clicked.connect(self.convertMesh)
        buttonLayout.addWidget(self.convertButton)
        
        self.checkMeshButton = QPushButton("Check Mesh", self)
        self.checkMeshButton.clicked.connect(self.checkMesh)
        buttonLayout.addWidget(self.checkMeshButton)
        
        self.decomposeParButton = QPushButton("Decompose Cores", self)
        self.decomposeParButton.clicked.connect(self.decomposePar)
        buttonLayout.addWidget(self.decomposeParButton)
        
        self.runButton = QPushButton("Run Simulation", self)
        self.runButton.setStyleSheet("background-color: green; color: white; font-weight: bold;")
        self.runButton.clicked.connect(self.runSimulation)
        
        self.stopButton = QPushButton("Stop Simulation", self)
        self.stopButton.setStyleSheet("background-color: red; color: white; font-weight: bold;")
        self.stopButton.clicked.connect(self.stopSimulation)
        
        self.reconstructButton = QPushButton("Reconstruct", self)
        self.reconstructButton.clicked.connect(self.reconstructPar)
        
        self.clearDecomposeButton = QPushButton("Clear Processors", self)
        self.clearDecomposeButton.clicked.connect(self.clearDecomposedProcessors)
        
        self.clearSimulationButton = QPushButton("Clear Simulation Files", self)
        self.clearSimulationButton.clicked.connect(self.clearSimulation)

        self.logButton = QPushButton("Show Logs (log.foamRun)", self)
        self.logButton.clicked.connect(self.showSimulationLogs)
        buttonLayout.addWidget(self.logButton)

        buttonLayout.addWidget(self.convertButton)
        buttonLayout.addWidget(self.decomposeParButton)
        buttonLayout.addWidget(self.runButton)
        buttonLayout.addWidget(self.stopButton)
        buttonLayout.addWidget(self.reconstructButton)
        buttonLayout.addWidget(self.clearDecomposeButton)
        buttonLayout.addWidget(self.clearSimulationButton)
        
        leftContentLayout.addLayout(buttonLayout)
        
        contentLayout.addLayout(leftContentLayout, 1)
        # contentLayout.addLayout(treeLayout, 1)
        
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
        
        self.meshPathLabel = QLabel("Mesh: None", self.statusBar)
        self.solverLabel = QLabel(f"Solver: {self.currentSolver}", self.statusBar)
        self.cpuUsageLabel = QLabel("CPU: --%", self.statusBar)
        self.memUsageLabel = QLabel("Memory: --%", self.statusBar)

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
        if not self.unvFilePath:
            self.outputArea.append("Erro: Nenhum caso selecionado")
            return
        
        caseDir = QFileInfo(self.unvFilePath).absolutePath()
        command = f"paraview --data={caseDir}/foam.foam"
        
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
        self.currentProcess.setWorkingDirectory(self.unvFilePath)

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
    
    def clearDecomposedProcessors(self):
        if not self.unvFilePath:
            self.outputArea.append("Erro: Nenhum caso selecionado.")
            return

        caseDir = QDir(self.unvFilePath)
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
        dialog.resize(300, 200)

        layout = QVBoxLayout(dialog)

        dLabel = QLabel("d (diâmetro):", dialog)
        dInput = QLineEdit(dialog)
        dInput.setPlaceholderText("Exemplo: 0.106")

        nLabel = QLabel("n (distância do bocal):", dialog)
        nInput = QLineEdit(dialog)
        nInput.setPlaceholderText("Exemplo: 30")

        mLabel = QLabel("m (distância de transição):", dialog)
        mInput = QLineEdit(dialog)
        mInput.setPlaceholderText("Exemplo: 10")

        dyIn0Label = QLabel("dy_in_0 (altura inicial):", dialog)
        dyIn0Input = QLineEdit(dialog)
        dyIn0Input.setPlaceholderText("Exemplo: 0.00142")

        dyWall0Label = QLabel("dy_wall_0 (altura na parede):", dialog)
        dyWall0Input = QLineEdit(dialog)
        dyWall0Input.setPlaceholderText("Exemplo: 0.008")

        calculateButton = QPushButton("Calcular", dialog)
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

        layout = QVBoxLayout(dialog)

        self.historyTable = QTableWidget(dialog)
        self.historyTable.setColumnCount(5)
        self.historyTable.setHorizontalHeaderLabels(["Solver", "Malha", "Início", "Fim", "Status"])
        self.loadHistoryIntoTable()
        layout.addWidget(self.historyTable)

        buttonLayout = QHBoxLayout()
        
        clearAllButton = QPushButton("Limpar Tudo", dialog)
        clearAllButton.clicked.connect(self.clearAllSimulations)
        buttonLayout.addWidget(clearAllButton)

        deleteSelectedButton = QPushButton("Excluir Selecionado", dialog)
        deleteSelectedButton.clicked.connect(self.deleteSelectedSimulation)
        buttonLayout.addWidget(deleteSelectedButton)

        layout.addLayout(buttonLayout)
        dialog.setLayout(layout)
        dialog.exec_()

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
        self.c0, self.c1, self.c2, self.c3 = 999.84, 0.0679, -0.0085, 0.0001
        self.A, self.B = 0.51, -0.0002  
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
        # self.searchBar.textChanged.connect(self.filterTreeView)
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
