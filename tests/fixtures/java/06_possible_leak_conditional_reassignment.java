import java.io.*;

public class PossibleLeakConditionalReassignment {
    public void riskyMethod(String path1, String path2, boolean flag) throws IOException {
        FileInputStream fis = new FileInputStream(path1);
        if (flag) {
            fis = new FileInputStream(path2);
        }
        fis.close();
    }
}
